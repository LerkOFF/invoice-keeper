import os
import tempfile

# Окружение выставляется до импорта приложения, чтобы тесты не трогали рабочую базу
_tmp = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp}/test.db"
os.environ["RECEIPTS_DIR"] = f"{_tmp}/receipts"
os.environ["SEED_DEMO_DATA"] = "false"
os.environ["SCHEDULER_ENABLED"] = "false"
os.environ["TELEGRAM_BUTTONS_ENABLED"] = "false"
os.environ["TELEGRAM_BOT_TOKEN"] = ""
os.environ["TELEGRAM_CHAT_ID"] = ""
os.environ["MAX_BUTTONS_ENABLED"] = "false"
os.environ["MAX_BOT_TOKEN"] = ""
os.environ["MAX_CHAT_ID"] = ""
os.environ["ADMIN_LOGIN"] = "boss"
os.environ["ADMIN_PASSWORD"] = "boss-pass-test"

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.db import Base
import app.models  # noqa: F401


@pytest.fixture
def db() -> Session:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


# ---------- общие фикстуры для API-тестов ----------

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import delete  # noqa: E402

from app.api.deps import current_date  # noqa: E402
from app.core.db import SessionLocal, init_db  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.main import create_app  # noqa: E402
from app.models import AuditEntry, AuthSession, PaymentOccurrence, RecurringPayment, User  # noqa: E402
from tests.helpers import ADMIN, B, TODAY, USER  # noqa: E402


@pytest.fixture(autouse=True)
def clean_db():
    """Чистая база и один обычный пользователь `ivan` перед каждым тестом."""
    init_db()
    with SessionLocal() as db:
        for model in (AuditEntry, AuthSession, PaymentOccurrence, RecurringPayment, User):
            db.execute(delete(model))
        db.add(User(login=USER["login"], password_hash=hash_password(USER["password"])))
        db.commit()


@pytest.fixture
def app():
    app = create_app()
    app.dependency_overrides[current_date] = lambda: TODAY
    return app


def logged_in(app, creds) -> TestClient:
    """Клиент с Bearer-токеном без cookie, чтобы роли разных клиентов не смешивались."""
    client = TestClient(app)
    client.__enter__()
    response = client.post(f"{B}/auth/login", json=creds)
    assert response.status_code == 200, response.text
    client.cookies.clear()
    client.headers["Authorization"] = f"Bearer {response.json()['token']}"
    return client


@pytest.fixture
def admin(app):
    client = logged_in(app, ADMIN)
    yield client
    client.__exit__(None, None, None)


@pytest.fixture
def user(app):
    client = logged_in(app, USER)
    yield client
    client.__exit__(None, None, None)


@pytest.fixture
def anon(app):
    with TestClient(app) as client:
        yield client
