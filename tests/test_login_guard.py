from fastapi.testclient import TestClient

from app.services.login_guard import LoginGuard, login_guard
from tests.helpers import ADMIN, B, USER


def attempt(client, login, password):
    return client.post(f"{B}/auth/login", json={"login": login, "password": password})


def test_five_failures_lock_the_login_even_for_right_password(app):
    client = TestClient(app)
    for _ in range(4):
        assert attempt(client, USER["login"], "wrong").status_code == 401
    locked = attempt(client, USER["login"], "wrong")
    assert locked.status_code == 429
    assert int(locked.headers["Retry-After"]) > 0 and "Попробуйте через 15 мин" in locked.json()["detail"]
    assert attempt(client, USER["login"], USER["password"]).status_code == 429
    # другой логин с того же адреса входит
    assert attempt(client, ADMIN["login"], ADMIN["password"]).status_code == 200


def test_success_resets_the_counter(app):
    client = TestClient(app)
    for _ in range(4):
        attempt(client, USER["login"], "wrong")
    assert attempt(client, USER["login"], USER["password"]).status_code == 200
    for _ in range(4):
        assert attempt(client, USER["login"], "wrong").status_code == 401


def test_lock_is_logged_without_password(app, admin):
    client = TestClient(app)
    for _ in range(5):
        attempt(client, "ivan", "secret-guess")
    entries = admin.get(f"{B}/audit-log", params={"action": "auth.login_locked"}).json()
    assert len(entries) == 1 and entries[0]["actor"] == "ivan" and entries[0]["details"] == {"minutes": 15}
    assert "secret-guess" not in str(admin.get(f"{B}/audit-log").json())


def test_lock_expires_after_window():
    now = [1000.0]
    guard = LoginGuard(clock=lambda: now[0])
    for _ in range(5):
        guard.failure("1.2.3.4", "Ivan", 900)
    assert guard.retry_after("1.2.3.4", "ivan", 5, 900) == 900  # регистр логина не важен
    assert guard.retry_after("5.6.7.8", "ivan", 5, 900) == 0  # другой адрес не заперт
    now[0] += 901
    assert guard.retry_after("1.2.3.4", "ivan", 5, 900) == 0


def test_many_logins_from_one_address_hit_the_address_limit():
    guard = LoginGuard(clock=lambda: 0.0)
    for i in range(20):
        guard.failure("1.2.3.4", f"user{i}", 900)
    assert guard.retry_after("1.2.3.4", "fresh-login", 5, 900) > 0


def test_guard_is_reset_between_tests():
    assert login_guard.retry_after("testclient", USER["login"], 5, 900) == 0
