from fastapi.testclient import TestClient

from app.main import create_app


def test_health_and_swagger_paths_use_api_prefix():
    with TestClient(create_app()) as client:
        assert client.get("/api/v1/health").json() == {"status": "ok"}
        assert client.get("/api/v1/docs").status_code == 200
        assert client.get("/api/v1/openapi.json").json()["info"]["title"] == "Invoice Keeper"
