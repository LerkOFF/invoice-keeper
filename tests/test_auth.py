from datetime import UTC, datetime, timedelta

import pytest
from fastapi import APIRouter
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.api.deps import AdminPrincipal, CurrentPrincipal
from app.core.db import SessionLocal, init_db
from app.core.security import hash_password
from app.main import create_app
from app.models import AuthSession, User

ADMIN = {"login": "boss", "password": "boss-pass-test"}
USER = {"login": "ivan", "password": "ivan-pass-123"}


@pytest.fixture(autouse=True)
def clean_db():
    init_db()
    with SessionLocal() as db:
        db.execute(delete(AuthSession))
        db.execute(delete(User))
        db.add(User(login=USER["login"], password_hash=hash_password(USER["password"])))
        db.commit()


@pytest.fixture
def client():
    app = create_app()
    probe = APIRouter(prefix="/api/v1/_probe")

    @probe.get("/any")
    def any_role(principal: CurrentPrincipal) -> dict:
        return {"login": principal.login}

    @probe.get("/admin")
    def admin_only(principal: AdminPrincipal) -> dict:
        return {"login": principal.login}

    app.include_router(probe)
    with TestClient(app) as c:
        yield c


def login(client, creds) -> str:
    response = client.post("/api/v1/auth/login", json=creds)
    assert response.status_code == 200, response.text
    return response.json()["token"]


def test_admin_login_and_me(client):
    body = client.post("/api/v1/auth/login", json=ADMIN).json()
    assert body["user"] == {"id": None, "login": "boss", "role": "admin"}

    me = client.get("/api/v1/auth/me")  # cookie проставлен логином
    assert me.status_code == 200
    assert me.json()["role"] == "admin"


def test_user_login_and_me(client):
    login(client, USER)
    me = client.get("/api/v1/auth/me").json()
    assert me["login"] == "ivan" and me["role"] == "user" and me["id"] is not None


@pytest.mark.parametrize(
    "creds",
    [
        {"login": "boss", "password": "wrong"},
        {"login": "ivan", "password": "wrong"},
        {"login": "ghost", "password": "whatever"},
    ],
)
def test_wrong_credentials_give_401(client, creds):
    response = client.post("/api/v1/auth/login", json=creds)
    assert response.status_code == 401
    assert "session" not in response.cookies


def test_no_auth_gives_401_everywhere(client):
    assert client.get("/api/v1/auth/me").status_code == 401
    assert client.post("/api/v1/auth/logout").status_code == 401
    assert client.get("/api/v1/_probe/any").status_code == 401
    assert client.get("/api/v1/_probe/admin").status_code == 401


def test_bearer_token_works_without_cookie(client):
    token = login(client, USER)
    client.cookies.clear()

    response = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200 and response.json()["login"] == "ivan"


def test_garbage_token_gives_401(client):
    response = client.get("/api/v1/auth/me", headers={"Authorization": "Bearer nonsense"})
    assert response.status_code == 401


def test_logout_ends_only_current_session(client):
    token_a = login(client, USER)
    client.cookies.clear()
    token_b = login(client, USER)

    client.post("/api/v1/auth/logout", headers={"Authorization": f"Bearer {token_a}"})

    assert client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token_a}"}).status_code == 401
    assert client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token_b}"}).status_code == 200


def test_logout_clears_cookie_session(client):
    login(client, ADMIN)
    assert client.post("/api/v1/auth/logout").status_code == 200
    assert client.get("/api/v1/auth/me").status_code == 401


def test_user_cannot_use_admin_routes_but_admin_can(client):
    login(client, USER)
    assert client.get("/api/v1/_probe/any").status_code == 200
    assert client.get("/api/v1/_probe/admin").status_code == 403

    client.cookies.clear()
    login(client, ADMIN)
    assert client.get("/api/v1/_probe/admin").status_code == 200


def test_token_is_stored_hashed(client):
    token = login(client, USER)
    with SessionLocal() as db:
        stored = db.scalars(select(AuthSession.token_hash)).all()
    assert token not in stored and len(stored) == 1 and len(stored[0]) == 64


def test_admin_password_change_in_env_closes_admin_sessions(client):
    from app.core.config import Settings, get_settings

    admin_token, user_token = login(client, ADMIN), login(client, USER)
    client.cookies.clear()
    me = lambda token: client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})  # noqa: E731
    assert me(admin_token).status_code == 200

    client.app.dependency_overrides[get_settings] = lambda: Settings(admin_password="rotated-pass")
    assert me(admin_token).status_code == 401
    assert me(user_token).status_code == 200  # сессии пользователей не задеты
    assert client.post("/api/v1/auth/login", json={**ADMIN, "password": "rotated-pass"}).status_code == 200


def test_admin_logout_removes_its_session(client):
    token = login(client, ADMIN)
    client.cookies.clear()
    headers = {"Authorization": f"Bearer {token}"}
    assert client.post("/api/v1/auth/logout", headers=headers).status_code == 200
    with SessionLocal() as db:
        assert db.scalar(select(AuthSession)) is None


def test_expired_session_is_rejected_and_removed(client):
    token = login(client, USER)
    with SessionLocal() as db:
        session = db.scalar(select(AuthSession))
        session.expires_at = datetime.now(UTC) - timedelta(minutes=1)
        db.commit()

    assert client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}).status_code == 401
    with SessionLocal() as db:
        assert db.scalar(select(AuthSession)) is None


def test_deleted_user_loses_access(client):
    token = login(client, USER)
    with SessionLocal() as db:
        db.execute(delete(User).where(User.login == "ivan"))
        db.commit()

    assert client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}).status_code == 401


def test_db_user_with_admin_login_cannot_get_admin(client):
    with SessionLocal() as db:
        db.add(User(login="boss", password_hash=hash_password("hacker-pass")))
        db.commit()

    assert client.post("/api/v1/auth/login", json={"login": "boss", "password": "hacker-pass"}).status_code == 401
    assert client.post("/api/v1/auth/login", json=ADMIN).json()["user"]["role"] == "admin"
