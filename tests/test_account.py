"""Безопасность и аккаунт: двухфакторный вход администратора, смена пароля, сессии, API-токены."""
import base64
import time
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine, inspect, select, text

from app.core.config import Settings, get_settings
from app.core.db import SessionLocal, migrate
from app.models import ApiToken, AuditEntry, AuthSession
from app.services import totp
from tests.helpers import ADMIN, B, USER

SECRET = totp.generate_secret()


def current_code(secret: str = SECRET) -> str:
    return totp.code_at(secret, int(time.time() // totp.STEP))


def other_code(code: str) -> str:
    return str((int(code) + 1) % 10**totp.DIGITS).zfill(totp.DIGITS)


def with_settings(app, **changes) -> None:
    settings = get_settings().model_copy(update=changes)
    app.dependency_overrides[get_settings] = lambda: settings


def client_for(app) -> TestClient:
    client = TestClient(app)
    client.__enter__()
    return client


def bearer(app, token: str) -> TestClient:
    client = client_for(app)
    client.headers["Authorization"] = f"Bearer {token}"
    return client


def login_token(app, creds) -> str:
    with TestClient(app) as client:
        response = client.post(f"{B}/auth/login", json=creds)
        assert response.status_code == 200, response.text
        return response.json()["token"]


def actions() -> list[str]:
    with SessionLocal() as db:
        return list(db.scalars(select(AuditEntry.action).order_by(AuditEntry.id)))


# ---------- TOTP: алгоритм ----------


def test_totp_matches_rfc_6238_vectors():
    # тестовые векторы RFC 6238 для SHA-1, последние 6 цифр
    secret = base64.b32encode(b"12345678901234567890").decode()
    assert totp.code_at(secret, 59 // 30) == "287082"
    assert totp.code_at(secret, 1111111109 // 30) == "081804"
    assert totp.code_at(secret, 2000000000 // 30) == "279037"


def test_totp_accepts_neighbour_step_only():
    now = 1_800_000_000.0
    counter = int(now // 30)
    assert totp.matching_counter(SECRET, totp.code_at(SECRET, counter - 1), now) == counter - 1
    assert totp.matching_counter(SECRET, totp.code_at(SECRET, counter + 1), now) == counter + 1
    assert totp.matching_counter(SECRET, totp.code_at(SECRET, counter - 3), now) is None
    assert totp.matching_counter(SECRET, "12345", now) is None
    assert totp.matching_counter(SECRET, "abcdef", now) is None


def test_totp_code_works_once():
    guard = totp.ReplayGuard()
    now = 1_800_000_000.0
    code = totp.code_at(SECRET, int(now // 30))
    assert guard.verify(SECRET, code, now)
    assert not guard.verify(SECRET, code, now)
    # старый код после использованного нового тоже не проходит
    assert not guard.verify(SECRET, totp.code_at(SECRET, int(now // 30) - 1), now)


def test_totp_secret_is_checked_at_startup():
    assert Settings(admin_totp_secret=" jbsw y3dp ehpk 3pxp ").admin_totp_secret == "JBSWY3DPEHPK3PXP"
    assert Settings(admin_totp_secret="").admin_totp_secret == ""
    for bad in ("not-base32!", "ABC"):
        with pytest.raises(ValidationError):
            Settings(admin_totp_secret=bad)


def test_provisioning_uri_for_authenticator_apps():
    uri = totp.provisioning_uri("JBSWY3DPEHPK3PXP", "admin")
    assert uri.startswith("otpauth://totp/Invoice%20Keeper%3Aadmin?")
    assert "secret=JBSWY3DPEHPK3PXP" in uri and "issuer=Invoice+Keeper" in uri


# ---------- TOTP: вход администратора ----------


@pytest.fixture
def otp_app(app):
    with_settings(app, admin_totp_secret=SECRET)
    return app


def test_admin_without_code_is_asked_for_it(otp_app, anon):
    response = anon.post(f"{B}/auth/login", json=ADMIN)
    assert response.status_code == 401
    assert response.headers["X-OTP-Required"] == "true"
    with SessionLocal() as db:
        assert db.scalar(select(AuthSession)) is None


def test_admin_signs_in_with_code(otp_app, anon):
    response = anon.post(f"{B}/auth/login", json={**ADMIN, "otp": current_code()})
    assert response.status_code == 200, response.text
    assert response.json()["user"]["two_factor"] is True
    assert anon.get(f"{B}/auth/me").json()["two_factor"] is True


def test_wrong_or_reused_code_is_refused_and_logged(otp_app, anon):
    code = current_code()
    wrong = anon.post(f"{B}/auth/login", json={**ADMIN, "otp": other_code(code)})
    assert wrong.status_code == 401 and wrong.headers["X-OTP-Required"] == "true"
    assert anon.post(f"{B}/auth/login", json={**ADMIN, "otp": code}).status_code == 200
    assert anon.post(f"{B}/auth/login", json={**ADMIN, "otp": code}).status_code == 401
    assert actions().count("auth.otp_failed") == 2


def test_code_does_not_help_with_wrong_password(otp_app, anon):
    response = anon.post(f"{B}/auth/login", json={**ADMIN, "password": "nope", "otp": current_code()})
    assert response.status_code == 401
    assert "X-OTP-Required" not in response.headers


def test_guessing_codes_locks_sign_in(otp_app, anon):
    code = current_code()
    for _ in range(get_settings().login_max_failures - 1):
        assert anon.post(f"{B}/auth/login", json={**ADMIN, "otp": other_code(code)}).status_code == 401
    assert anon.post(f"{B}/auth/login", json={**ADMIN, "otp": other_code(code)}).status_code == 429
    # даже верный код не пускает, пока вход закрыт
    assert anon.post(f"{B}/auth/login", json={**ADMIN, "otp": code}).status_code == 429


def test_users_do_not_need_a_code(otp_app, anon):
    assert anon.post(f"{B}/auth/login", json=USER).status_code == 200


def test_enabling_2fa_ends_old_admin_sessions(app):
    token = login_token(app, ADMIN)
    client = bearer(app, token)
    assert client.get(f"{B}/auth/me").status_code == 200
    with_settings(app, admin_totp_secret=SECRET)
    assert client.get(f"{B}/auth/me").status_code == 401


# ---------- смена пароля ----------


def test_user_changes_password(app, user):
    other = bearer(app, login_token(app, USER))
    new = {"current_password": USER["password"], "new_password": "brand-new-pass"}

    response = user.post(f"{B}/auth/password", json=new)
    assert response.status_code == 200, response.text
    assert response.json() == {"ended_sessions": 1}

    assert user.get(f"{B}/auth/me").status_code == 200  # текущая сессия осталась
    assert other.get(f"{B}/auth/me").status_code == 401  # остальные закрыты
    with TestClient(app) as anon:
        assert anon.post(f"{B}/auth/login", json=USER).status_code == 401
        assert anon.post(f"{B}/auth/login", json={**USER, "password": "brand-new-pass"}).status_code == 200
    assert "auth.password_changed" in actions()


def test_wrong_current_password_counts_as_failure(app, user):
    body = {"current_password": "wrong-pass", "new_password": "brand-new-pass"}
    for _ in range(get_settings().login_max_failures - 1):
        response = user.post(f"{B}/auth/password", json=body)
        assert response.status_code == 400 and response.json()["detail"] == "Неверный текущий пароль"
    assert user.post(f"{B}/auth/password", json=body).status_code == 429
    assert user.post(f"{B}/auth/password", json={**body, "current_password": USER["password"]}).status_code == 429
    assert "auth.password_failed" in actions()


@pytest.mark.parametrize(
    "body",
    [
        {"current_password": USER["password"], "new_password": "short"},
        {"current_password": USER["password"]},
        {"current_password": USER["password"], "new_password": "brand-new-pass", "login": "other"},
    ],
)
def test_password_change_validation(user, body):
    assert user.post(f"{B}/auth/password", json=body).status_code == 422


def test_new_password_must_differ(user):
    body = {"current_password": USER["password"], "new_password": USER["password"]}
    assert user.post(f"{B}/auth/password", json=body).status_code == 400


def test_admin_password_lives_in_env(admin):
    body = {"current_password": ADMIN["password"], "new_password": "brand-new-pass"}
    assert admin.post(f"{B}/auth/password", json=body).status_code == 403


# ---------- мои сессии ----------


def test_sessions_list_own_only_current_first(app, user, admin):
    login_token(app, USER)
    sessions = user.get(f"{B}/auth/sessions").json()
    assert len(sessions) == 2
    assert sessions[0]["current"] is True and sessions[1]["current"] is False
    assert sessions[0]["ip"] == "testclient" and sessions[0]["user_agent"].startswith("testclient")
    assert {"created_at", "expires_at", "last_seen_at"} <= sessions[0].keys()
    # у администратора свой список
    assert [s["current"] for s in admin.get(f"{B}/auth/sessions").json()] == [True]


def test_end_one_session(app, user, admin):
    other = bearer(app, login_token(app, USER))
    sessions = user.get(f"{B}/auth/sessions").json()
    current, second = sessions[0]["id"], sessions[1]["id"]

    assert user.delete(f"{B}/auth/sessions/{current}").status_code == 400
    assert admin.delete(f"{B}/auth/sessions/{second}").status_code == 404  # чужую не завершить
    assert user.delete(f"{B}/auth/sessions/{second}").status_code == 204
    assert other.get(f"{B}/auth/me").status_code == 401
    assert user.delete(f"{B}/auth/sessions/{second}").status_code == 404
    assert "auth.session_ended" in actions()


def test_end_other_sessions(app, user, admin):
    others = [bearer(app, login_token(app, USER)) for _ in range(2)]
    assert user.post(f"{B}/auth/sessions/end-others").json() == {"ended": 2}
    assert all(c.get(f"{B}/auth/me").status_code == 401 for c in others)
    assert user.get(f"{B}/auth/me").status_code == 200
    assert admin.get(f"{B}/auth/me").status_code == 200  # чужие сессии не тронуты


def test_admin_list_hides_sessions_of_old_credentials(app):
    login_token(app, ADMIN)
    with_settings(app, admin_password="rotated-pass-1")
    client = bearer(app, login_token(app, {**ADMIN, "password": "rotated-pass-1"}))
    assert len(client.get(f"{B}/auth/sessions").json()) == 1
    with SessionLocal() as db:
        assert len(db.scalars(select(AuthSession)).all()) == 1  # прежняя удалена


def test_migration_adds_session_columns(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path}/old.db")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE payment_occurrences (id INTEGER PRIMARY KEY, recurring_id INTEGER)"))
        conn.execute(text("CREATE TABLE recurring_payments (id INTEGER PRIMARY KEY, amount_minor INTEGER)"))
        conn.execute(text("CREATE TABLE sessions (id INTEGER PRIMARY KEY, token_hash TEXT, is_admin BOOLEAN)"))
    migrate(engine)
    migrate(engine)
    columns = {c["name"] for c in inspect(engine).get_columns("sessions")}
    assert {"ip", "user_agent", "last_seen_at", "key_tag"} <= columns


# ---------- API-токены ----------


def make_token(client, scope="read", **extra) -> dict:
    response = client.post(f"{B}/me/tokens", json={"name": "Скрипт", "scope": scope, **extra})
    assert response.status_code == 201, response.text
    return response.json()


def test_token_is_shown_once(user):
    created = make_token(user, expires_in_days=30)
    assert created["token"].startswith("ik_") and created["token"].startswith(created["prefix"])
    listed = user.get(f"{B}/me/tokens").json()
    assert [t["id"] for t in listed] == [created["id"]]
    assert "token" not in listed[0] and listed[0]["expires_at"] is not None
    with SessionLocal() as db:
        row = db.get(ApiToken, created["id"])
        assert created["token"] not in (row.token_hash, row.prefix)
        entry = db.scalar(select(AuditEntry).where(AuditEntry.action == "token.create"))
        assert created["token"] not in str(entry.details)


def test_read_token_only_reads(app, user):
    client = bearer(app, make_token(user, "read")["token"])
    assert client.get(f"{B}/payment-occurrences").status_code == 200
    assert client.get(f"{B}/auth/me").json()["via_token"] is True
    response = client.patch(f"{B}/payment-occurrences/1", json={"status": "paid"})
    assert response.status_code == 403 and response.json()["detail"] == "API-токен только для чтения"


def test_write_token_acts_with_owner_rights(app, admin, user):
    admin_client = bearer(app, make_token(admin, "write")["token"])
    assert admin_client.post(f"{B}/users", json={"login": "petr", "password": "petr-pass-123"}).status_code == 201
    user_client = bearer(app, make_token(user, "write")["token"])
    assert user_client.get(f"{B}/users").status_code == 403  # права владельца, не больше


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/me/tokens"),
        ("POST", "/me/tokens"),
        ("DELETE", "/me/tokens/1"),
        ("POST", "/auth/password"),
        ("GET", "/auth/sessions"),
        ("POST", "/auth/sessions/end-others"),
        ("POST", "/auth/logout"),
    ],
)
def test_token_cannot_manage_the_account(app, user, method, path):
    client = bearer(app, make_token(user, "write")["token"])
    assert client.request(method, f"{B}{path}", json={}).status_code == 403


def test_revoked_expired_and_orphan_tokens_stop_working(app, admin, user):
    revoked = make_token(user)
    client = bearer(app, revoked["token"])
    assert admin.delete(f"{B}/me/tokens/{revoked['id']}").status_code == 404  # чужой не отозвать
    assert user.delete(f"{B}/me/tokens/{revoked['id']}").status_code == 204
    assert client.get(f"{B}/auth/me").status_code == 401

    expired = make_token(user)
    with SessionLocal() as db:
        db.get(ApiToken, expired["id"]).expires_at = datetime.now(UTC) - timedelta(minutes=1)
        db.commit()
    assert bearer(app, expired["token"]).get(f"{B}/auth/me").status_code == 401

    orphan = bearer(app, make_token(user)["token"])
    user_id = user.get(f"{B}/auth/me").json()["id"]
    assert admin.delete(f"{B}/users/{user_id}").status_code == 204
    assert orphan.get(f"{B}/auth/me").status_code == 401
    assert actions().count("token.revoke") == 1


def test_admin_token_is_bound_to_env_credentials(app, admin):
    client = bearer(app, make_token(admin)["token"])
    assert client.get(f"{B}/users").status_code == 200
    with_settings(app, admin_password="rotated-pass-1")
    assert client.get(f"{B}/users").status_code == 401


def test_token_last_used_is_recorded(app, user):
    created = make_token(user)
    assert user.get(f"{B}/me/tokens").json()[0]["last_used_at"] is None
    bearer(app, created["token"]).get(f"{B}/payment-occurrences")
    assert user.get(f"{B}/me/tokens").json()[0]["last_used_at"] is not None


@pytest.mark.parametrize(
    "body",
    [
        {"name": "  ", "scope": "read"},
        {"name": "x", "scope": "admin"},
        {"name": "x", "scope": "read", "expires_in_days": 0},
        {"name": "x", "scope": "read", "user_id": 1},
        {"scope": "read"},
    ],
)
def test_token_validation(user, body):
    assert user.post(f"{B}/me/tokens", json=body).status_code == 422


def test_token_limit(user):
    from app.services.api_tokens import MAX_TOKENS

    for _ in range(MAX_TOKENS):
        make_token(user)
    assert user.post(f"{B}/me/tokens", json={"name": "лишний", "scope": "read"}).status_code == 409
