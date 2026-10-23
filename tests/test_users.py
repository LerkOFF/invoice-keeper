import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.db import SessionLocal
from app.core.security import hash_password
from app.models import AuthSession, User
from tests.helpers import ADMIN, B, USER

NEW = {"login": "petr", "password": "petr-pass-123"}


def create(admin, **body):
    return admin.post(f"{B}/users", json={**NEW, **body})


def login(app, creds) -> TestClient:
    client = TestClient(app)
    client.__enter__()
    response = client.post(f"{B}/auth/login", json=creds)
    return client, response


def user_id(login_name: str) -> int:
    with SessionLocal() as db:
        return db.scalar(select(User.id).where(User.login == login_name))


# ---------- доступ ----------


def test_users_api_is_admin_only(admin, user, anon):
    target = user_id("ivan")
    calls = [
        ("get", "/users", None),
        ("post", "/users", NEW),
        ("patch", f"/users/{target}", {"password": "new-pass-123"}),
        ("delete", f"/users/{target}", None),
    ]
    for method, path, body in calls:
        kwargs = {"json": body} if body is not None else {}
        assert getattr(anon, method)(f"{B}{path}", **kwargs).status_code == 401, (method, path)
        assert getattr(user, method)(f"{B}{path}", **kwargs).status_code == 403, (method, path)


def test_user_with_invalid_body_still_gets_403_not_422(user):
    assert user.post(f"{B}/users", json={"login": "x"}).status_code == 403


# ---------- создание и список ----------


def test_admin_creates_user_who_can_log_in(admin, app):
    response = create(admin)
    assert response.status_code == 201
    body = response.json()
    assert body["login"] == "petr" and body["role"] == "user" and "password" not in body
    assert "password_hash" not in body

    client, login_response = login(app, NEW)
    assert login_response.status_code == 200 and login_response.json()["user"]["role"] == "user"
    client.__exit__(None, None, None)


def test_list_returns_regular_users_without_secrets_and_without_admin(admin):
    create(admin)
    items = admin.get(f"{B}/users").json()
    assert [u["login"] for u in items] == ["ivan", "petr"]
    assert all(set(u) == {"id", "login", "role", "created_at", "messengers"} for u in items)
    assert all(u["role"] == "user" for u in items)


def test_password_is_stored_hashed():
    from app.core.config import get_settings
    from app.services.users import create_user

    with SessionLocal() as db:
        user = create_user(db, get_settings(), "hashed", "plain-pass-123")
        assert user.password_hash != "plain-pass-123" and user.password_hash.startswith("$argon2")


@pytest.mark.parametrize(
    "body",
    [
        {"login": "ab"},
        {"login": "has space"},
        {"login": "кириллица"},
        {"login": ""},
        {"password": "short"},
        {"password": ""},
        {"role": "admin"},  # создать администратора через API нельзя
        {"is_admin": True},
    ],
)
def test_create_validation(admin, body):
    assert create(admin, **body).status_code == 422


def test_duplicate_login_is_conflict_case_insensitive(admin):
    assert create(admin).status_code == 201
    assert create(admin).status_code == 409
    assert create(admin, login="PETR").status_code == 409
    assert create(admin, login="Ivan").status_code == 409


@pytest.mark.parametrize("login", ["boss", "BOSS", "Boss"])
def test_admin_login_is_reserved(admin, login):
    response = create(admin, login=login)
    assert response.status_code == 409
    with SessionLocal() as db:
        assert db.scalar(select(User).where(User.login == login)) is None


# ---------- изменение ----------


def test_change_password_and_old_one_stops_working(admin, app):
    target = user_id("ivan")
    assert admin.patch(f"{B}/users/{target}", json={"password": "brand-new-pass"}).status_code == 200

    _, old = login(app, USER)
    _, new = login(app, {"login": "ivan", "password": "brand-new-pass"})
    assert old.status_code == 401 and new.status_code == 200


def test_change_password_ends_user_sessions(admin, user):
    assert user.get(f"{B}/auth/me").status_code == 200
    admin.patch(f"{B}/users/{user_id('ivan')}", json={"password": "brand-new-pass"})
    assert user.get(f"{B}/auth/me").status_code == 401


def test_change_login(admin, app):
    target = user_id("ivan")
    assert admin.patch(f"{B}/users/{target}", json={"login": "ivan2"}).json()["login"] == "ivan2"
    _, response = login(app, {"login": "ivan2", "password": USER["password"]})
    assert response.status_code == 200


def test_change_login_conflicts(admin):
    create(admin)
    target = user_id("ivan")
    assert admin.patch(f"{B}/users/{target}", json={"login": "petr"}).status_code == 409
    assert admin.patch(f"{B}/users/{target}", json={"login": "PETR"}).status_code == 409
    assert admin.patch(f"{B}/users/{target}", json={"login": "boss"}).status_code == 409
    assert admin.patch(f"{B}/users/{target}", json={"login": "BOSS"}).status_code == 409


def test_keeping_own_login_is_not_a_conflict(admin):
    target = user_id("ivan")
    assert admin.patch(f"{B}/users/{target}", json={"login": "ivan"}).status_code == 200
    assert admin.patch(f"{B}/users/{target}", json={"login": "IVAN"}).status_code == 200


@pytest.mark.parametrize(
    "body",
    [{}, {"role": "admin"}, {"login": "x"}, {"password": "short"}, {"id": 5}],
)
def test_patch_validation_and_role_cannot_change(admin, body):
    assert admin.patch(f"{B}/users/{user_id('ivan')}", json=body).status_code == 422


def test_patch_unknown_user(admin):
    assert admin.patch(f"{B}/users/9999", json={"password": "new-pass-123"}).status_code == 404


# ---------- удаление ----------


def test_delete_user_removes_access(admin, user):
    target = user_id("ivan")
    assert admin.delete(f"{B}/users/{target}").status_code == 204

    assert user.get(f"{B}/auth/me").status_code == 401
    assert [u["login"] for u in admin.get(f"{B}/users").json()] == []
    with SessionLocal() as db:
        assert all(s.user_id != target for s in db.scalars(select(AuthSession)))


def test_delete_unknown_and_twice(admin):
    assert admin.delete(f"{B}/users/9999").status_code == 404
    target = user_id("ivan")
    admin.delete(f"{B}/users/{target}")
    assert admin.delete(f"{B}/users/{target}").status_code == 404


# ---------- защита администратора ----------


def test_admin_is_not_in_users_table_or_list(admin):
    with SessionLocal() as db:
        assert db.scalar(select(User).where(User.login == "boss")) is None
    assert "boss" not in [u["login"] for u in admin.get(f"{B}/users").json()]


def test_user_cannot_promote_himself_or_edit_others(user):
    target = user_id("ivan")
    assert user.patch(f"{B}/users/{target}", json={"role": "admin"}).status_code == 403
    assert user.patch(f"{B}/users/{target}", json={"password": "hacked-pass-1"}).status_code == 403
    assert user.delete(f"{B}/users/{target}").status_code == 403


def test_admin_role_record_in_db_cannot_be_managed_via_api(admin):
    with SessionLocal() as db:
        db.add(User(login="shadow", password_hash=hash_password("shadow-pass-1"), role="admin"))
        db.commit()
    target = user_id("shadow")

    assert "shadow" not in [u["login"] for u in admin.get(f"{B}/users").json()]
    assert admin.patch(f"{B}/users/{target}", json={"password": "changed-pass-1"}).status_code == 403
    assert admin.patch(f"{B}/users/{target}", json={"login": "other"}).status_code == 403
    assert admin.delete(f"{B}/users/{target}").status_code == 403
    with SessionLocal() as db:
        assert db.scalar(select(User).where(User.login == "shadow")) is not None


def test_env_admin_keeps_working_after_all_user_operations(admin, app):
    create(admin)
    admin.patch(f"{B}/users/{user_id('petr')}", json={"login": "petr2"})
    admin.delete(f"{B}/users/{user_id('petr2')}")

    _, response = login(app, ADMIN)
    assert response.status_code == 200 and response.json()["user"]["role"] == "admin"


def test_created_at_is_marked_as_utc(admin):
    created = create(admin).json()["created_at"]
    assert created.endswith("Z")
