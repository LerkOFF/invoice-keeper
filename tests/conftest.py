import os
import tempfile

# Окружение выставляется до импорта приложения, чтобы тесты не трогали рабочую базу
os.environ["DATABASE_URL"] = f"sqlite:///{tempfile.mkdtemp()}/test.db"
os.environ["SEED_DEMO_DATA"] = "false"
os.environ["ADMIN_LOGIN"] = "boss"
os.environ["ADMIN_PASSWORD"] = "boss-pass-test"
os.environ["SECRET_KEY"] = "test-secret"

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
