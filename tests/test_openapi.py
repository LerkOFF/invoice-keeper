import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from openapi_spec_validator import validate

ROOT = Path(__file__).resolve().parent.parent
SPEC = ROOT / "openapi.yaml"

# Обязательные эндпоинты из задания: метод и путь буквально
REQUIRED = [
    ("post", "/api/v1/auth/login"),
    ("get", "/api/v1/auth/me"),
    ("post", "/api/v1/auth/logout"),
    ("get", "/api/v1/recurring-payments"),
    ("post", "/api/v1/recurring-payments"),
    ("delete", "/api/v1/recurring-payments/{id}"),
    ("get", "/api/v1/payment-occurrences"),
    ("get", "/api/v1/payment-occurrences/{id}"),
    ("patch", "/api/v1/payment-occurrences/{id}"),
    ("get", "/api/v1/payments/summary"),
    ("get", "/api/v1/users"),
    ("post", "/api/v1/users"),
    ("patch", "/api/v1/users/{id}"),
    ("delete", "/api/v1/users/{id}"),
]


@pytest.fixture(scope="module")
def spec() -> dict:
    assert SPEC.exists(), "в корне репозитория должен лежать openapi.yaml"
    return yaml.safe_load(SPEC.read_text(encoding="utf-8"))


def test_spec_is_valid_openapi(spec):
    validate(spec)


def test_spec_has_every_required_endpoint(spec):
    missing = [(m, p) for m, p in REQUIRED if m not in spec["paths"].get(p, {})]
    assert not missing, f"в спецификации нет: {missing}"


def test_spec_documents_auth_and_errors(spec):
    assert "HTTPBearer" in spec["components"]["securitySchemes"]
    patch = spec["paths"]["/api/v1/payment-occurrences/{id}"]["patch"]
    assert {"409", "422"} <= set(patch["responses"])


def test_swagger_serves_the_same_spec(anon, spec):
    live = anon.get("/api/v1/openapi.json").json()
    assert set(live["paths"]) == set(spec["paths"])
    assert anon.get("/api/v1/docs").status_code == 200


def test_spec_file_is_up_to_date():
    """Если упало: запустите `python scripts/export_openapi.py` и закоммитьте openapi.yaml."""
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "export_openapi.py"), "--check"], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr or result.stdout
