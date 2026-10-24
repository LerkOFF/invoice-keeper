"""Сквозная проверка требований ТЗ к доступу по всем ручкам API сразу, включая будущие."""
import re

import pytest

from app.main import create_app
from tests.helpers import B

# Ручки без входа: сам вход и проверка работоспособности
PUBLIC = {("POST", f"{B}/auth/login"), ("GET", f"{B}/health")}

# Действия администратора. Новая админская ручка должна попасть сюда осознанно
ADMIN_ONLY = {
    ("POST", f"{B}/recurring-payments"),
    ("PATCH", f"{B}/recurring-payments/{{id}}"),
    ("DELETE", f"{B}/recurring-payments/{{id}}"),
    ("POST", f"{B}/recurring-payments/{{id}}/pause"),
    ("POST", f"{B}/recurring-payments/{{id}}/resume"),
    ("GET", f"{B}/recurring-payments/import/template"),
    ("POST", f"{B}/recurring-payments/import"),
    ("GET", f"{B}/users"),
    ("POST", f"{B}/users"),
    ("PATCH", f"{B}/users/{{id}}"),
    ("DELETE", f"{B}/users/{{id}}"),
    ("GET", f"{B}/audit-log"),
    ("GET", f"{B}/auth/2fa"),
    ("POST", f"{B}/auth/2fa/setup"),
    ("POST", f"{B}/auth/2fa/enable"),
    ("POST", f"{B}/auth/2fa/disable"),
}

# Все ручки из схемы OpenAPI: новая ручка попадёт в проверку сама
ENDPOINTS = sorted(
    (method.upper(), path)
    for path, ops in create_app().openapi()["paths"].items()
    for method in ops
    if method in {"get", "post", "put", "patch", "delete"}
)


def _url(path: str) -> str:
    return re.sub(r"\{[^}]+\}", "1", path)


def test_schema_lists_the_api():
    assert len(ENDPOINTS) > 20 and PUBLIC <= set(ENDPOINTS) and ADMIN_ONLY <= set(ENDPOINTS)


@pytest.mark.parametrize(("method", "path"), [e for e in ENDPOINTS if e not in PUBLIC])
def test_every_endpoint_needs_login(anon, method, path):
    response = anon.request(method, _url(path), json={})
    assert response.status_code == 401, response.text


def test_user_is_refused_exactly_on_admin_actions(user):
    # тело заведомо неполное: отказ по правам должен прийти раньше проверки тела
    # выход пропускаем, иначе сессия кончится посреди обхода
    checked = [e for e in ENDPOINTS if e != ("POST", f"{B}/auth/logout")]
    refused = {(m, p) for m, p in checked if user.request(m, _url(p), json={}).status_code == 403}
    assert refused == ADMIN_ONLY


@pytest.mark.parametrize("token", ["nonsense", "Bearer", "a" * 64])
def test_forged_tokens_give_401(anon, token):
    assert anon.get(f"{B}/payment-occurrences", headers={"Authorization": f"Bearer {token}"}).status_code == 401
    anon.cookies.set("session", token)
    assert anon.get(f"{B}/payment-occurrences").status_code == 401
