"""Двухфакторный вход администратора, включённый из панели (без ADMIN_TOTP_SECRET в .env)."""
import time

import pytest
from fastapi.testclient import TestClient

from app.core.db import SessionLocal
from app.models import AdminTwoFactor
from app.services import totp, two_factor
from app.services.totp import admin_otp
from tests.helpers import ADMIN, B, USER
from tests.test_account import SECRET, actions, bearer, current_code, login_token, other_code, with_settings


def code_for(secret: str) -> str:
    # каждый код принимается один раз: перед новым кодом того же шага забываем прежний, как будто прошло 30 секунд
    admin_otp.reset()
    return totp.code_at(secret, int(time.time() // totp.STEP))


def start(admin: TestClient) -> dict:
    response = admin.post(f"{B}/auth/2fa/setup")
    assert response.status_code == 200, response.text
    return response.json()


def turn_on(admin: TestClient) -> str:
    secret = start(admin)["secret"]
    response = admin.post(f"{B}/auth/2fa/enable", json={"code": code_for(secret)})
    assert response.status_code == 200, response.text
    return secret


def test_off_by_default(admin):
    assert admin.get(f"{B}/auth/2fa").json() == {"enabled": False, "source": None, "enabled_at": None}
    assert admin.get(f"{B}/auth/me").json()["two_factor"] is False


def test_setup_gives_secret_link_and_qr_without_changing_sign_in(app, admin, anon):
    setup = start(admin)
    assert setup["uri"].startswith(f"otpauth://totp/Invoice%20Keeper%3A{ADMIN['login']}?")
    assert f"secret={setup['secret']}" in setup["uri"]
    qr = setup["qr"]
    assert len(qr) >= 21 and all(len(row) == len(qr) and set(row) <= {"0", "1"} for row in qr)
    assert admin.get(f"{B}/auth/2fa").json()["enabled"] is False
    # пока секрет не подтверждён, хватает пароля
    assert anon.post(f"{B}/auth/login", json=ADMIN).status_code == 200


def test_enable_needs_the_code_from_the_new_secret(admin):
    secret = start(admin)["secret"]
    wrong = admin.post(f"{B}/auth/2fa/enable", json={"code": other_code(code_for(secret))})
    assert wrong.status_code == 400
    assert admin.get(f"{B}/auth/2fa").json()["enabled"] is False
    # повторная настройка выдаёт новый секрет, старый уже не подходит
    fresh = start(admin)["secret"]
    assert fresh != secret
    assert admin.post(f"{B}/auth/2fa/enable", json={"code": code_for(secret)}).status_code == 400


def test_enable_without_setup_is_refused(admin):
    response = admin.post(f"{B}/auth/2fa/enable", json={"code": "123456"})
    assert response.status_code == 400
    assert "настройку" in response.json()["detail"]


def test_enabled_from_panel_sign_in_needs_code(app, admin, anon):
    other = bearer(app, login_token(app, ADMIN))
    secret = start(admin)["secret"]
    response = admin.post(f"{B}/auth/2fa/enable", json={"code": code_for(secret)})
    assert response.status_code == 200, response.text
    assert response.json() == {"ended_sessions": 1}

    # текущая сессия осталась, другая закрыта
    assert admin.get(f"{B}/auth/me").json()["two_factor"] is True
    assert other.get(f"{B}/auth/me").status_code == 401
    status = admin.get(f"{B}/auth/2fa").json()
    assert status["enabled"] is True and status["source"] == "panel" and status["enabled_at"]

    asked = anon.post(f"{B}/auth/login", json=ADMIN)
    assert asked.status_code == 401 and asked.headers["X-OTP-Required"] == "true"
    assert anon.post(f"{B}/auth/login", json={**ADMIN, "otp": code_for(secret)}).status_code == 200
    assert "auth.2fa_enabled" in actions()


def test_already_enabled_cannot_be_set_up_again(admin):
    turn_on(admin)
    assert admin.post(f"{B}/auth/2fa/setup").status_code == 409
    assert admin.post(f"{B}/auth/2fa/enable", json={"code": "123456"}).status_code == 409


def test_disable_needs_password_and_code(admin, anon):
    secret = turn_on(admin)

    wrong_password = admin.post(f"{B}/auth/2fa/disable", json={"password": "nope", "code": code_for(secret)})
    assert wrong_password.status_code == 400
    wrong_code = admin.post(f"{B}/auth/2fa/disable", json={"password": ADMIN["password"], "code": other_code(code_for(secret))})
    assert wrong_code.status_code == 400
    assert admin.get(f"{B}/auth/2fa").json()["enabled"] is True
    assert {"auth.password_failed", "auth.otp_failed"} <= set(actions())

    ok = admin.post(f"{B}/auth/2fa/disable", json={"password": ADMIN["password"], "code": code_for(secret)})
    assert ok.status_code == 204, ok.text
    assert admin.get(f"{B}/auth/2fa").json()["enabled"] is False
    assert anon.post(f"{B}/auth/login", json=ADMIN).status_code == 200
    assert "auth.2fa_disabled" in actions()
    assert admin.post(f"{B}/auth/2fa/disable", json={"password": ADMIN["password"], "code": "123456"}).status_code == 409


def test_guessing_disable_codes_locks(app, admin):
    secret = turn_on(admin)
    with_settings(app, login_max_failures=3)
    bad = {"password": ADMIN["password"], "code": other_code(code_for(secret))}
    assert admin.post(f"{B}/auth/2fa/disable", json=bad).status_code == 400
    assert admin.post(f"{B}/auth/2fa/disable", json=bad).status_code == 400
    assert admin.post(f"{B}/auth/2fa/disable", json=bad).status_code == 429
    good = {"password": ADMIN["password"], "code": code_for(secret)}
    assert admin.post(f"{B}/auth/2fa/disable", json=good).status_code == 429


def test_secret_from_env_wins_and_is_read_only_in_panel(app, admin, anon):
    turn_on(admin)
    with_settings(app, admin_totp_secret=SECRET)
    admin_otp.reset()
    client = bearer(app, login_token(app, {**ADMIN, "otp": current_code()}))

    assert client.get(f"{B}/auth/2fa").json() == {"enabled": True, "source": "env", "enabled_at": None}
    assert client.post(f"{B}/auth/2fa/setup").status_code == 409
    assert client.post(f"{B}/auth/2fa/disable", json={"password": ADMIN["password"], "code": "123456"}).status_code == 409
    # код из панели при секрете в .env не подходит
    with SessionLocal() as db:
        panel_secret = db.get(AdminTwoFactor, 1).secret
    assert anon.post(f"{B}/auth/login", json={**ADMIN, "otp": code_for(panel_secret)}).status_code == 401


@pytest.mark.parametrize(("method", "path"), [("GET", "/auth/2fa"), ("POST", "/auth/2fa/setup")])
def test_only_admin_session_manages_it(app, user, admin, method, path):
    assert user.request(method, f"{B}{path}").status_code == 403
    token = admin.post(f"{B}/me/tokens", json={"name": "ci", "scope": "write"}).json()["token"]
    assert bearer(app, token).request(method, f"{B}{path}").status_code == 403


def test_users_still_sign_in_with_password_only(admin, anon):
    turn_on(admin)
    assert anon.post(f"{B}/auth/login", json=USER).status_code == 200


def test_recovery_command_turns_it_off(admin, anon, capsys):
    turn_on(admin)
    assert two_factor.main(["off"]) == 0
    assert "выключен" in capsys.readouterr().out
    assert anon.post(f"{B}/auth/login", json=ADMIN).status_code == 200
    assert two_factor.main([]) == 2
