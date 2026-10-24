from fastapi.testclient import TestClient

from tests.helpers import ADMIN, B, USER


def login(app, creds):
    client = TestClient(app)
    response = client.post(f"{B}/auth/login", json=creds)
    assert response.status_code == 200, response.text
    client.cookies.clear()
    client.headers["Authorization"] = f"Bearer {response.json()['token']}"
    return client


def change(client, current, new):
    return client.post(f"{B}/auth/password", json={"current_password": current, "new_password": new})


def test_user_changes_own_password_and_other_sessions_end(app):
    first, second = login(app, USER), login(app, USER)
    assert change(first, USER["password"], "new-secret-123").status_code == 204

    assert first.get(f"{B}/auth/me").status_code == 200  # текущая сессия жива
    assert second.get(f"{B}/auth/me").status_code == 401  # остальные завершены
    assert TestClient(app).post(f"{B}/auth/login", json=USER).status_code == 401
    assert TestClient(app).post(f"{B}/auth/login", json={**USER, "password": "new-secret-123"}).status_code == 200


def test_wrong_current_password_and_same_password_are_rejected(app):
    client = login(app, USER)
    wrong = change(client, "not-my-password", "new-secret-123")
    assert wrong.status_code == 400 and "неверный" in wrong.json()["detail"]
    same = change(client, USER["password"], USER["password"])
    assert same.status_code == 400 and "совпадает" in same.json()["detail"]
    assert change(client, USER["password"], "short").status_code == 422


def test_guessing_current_password_is_throttled(app):
    client = login(app, USER)
    for _ in range(4):
        assert change(client, "guess", "new-secret-123").status_code == 400
    assert change(client, "guess", "new-secret-123").status_code == 400
    assert change(client, USER["password"], "new-secret-123").status_code == 429


def test_admin_password_lives_in_env(app):
    admin = login(app, ADMIN)
    response = change(admin, ADMIN["password"], "another-admin-pass")
    assert response.status_code == 403 and ".env" in response.json()["detail"]


def test_change_is_logged_without_passwords(app, admin):
    client = login(app, USER)
    change(client, USER["password"], "new-secret-123")
    entries = admin.get(f"{B}/audit-log", params={"action": "auth.password_changed"}).json()
    assert len(entries) == 1 and entries[0]["actor"] == USER["login"]
    assert "new-secret-123" not in str(admin.get(f"{B}/audit-log").json())


def test_needs_login(anon):
    assert anon.post(f"{B}/auth/password", json={"current_password": "x", "new_password": "y" * 8}).status_code == 401
