import logging
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI

from app.api import auth
from app.core.clock import today
from app.core.config import get_settings
from app.core.db import SessionLocal, init_db
from app.seed import seed_demo_data
from app.services.periods import ensure_all_occurrences

API_PREFIX = "/api/v1"

logger = logging.getLogger("invoice_keeper")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    settings = get_settings()
    if "change-me" in (settings.admin_password, settings.secret_key):
        logger.warning("ADMIN_PASSWORD или SECRET_KEY остались значениями по умолчанию, поменяйте их в .env")
    init_db()
    with SessionLocal() as db:
        if settings.seed_demo_data:
            seed_demo_data(db, settings)
        ensure_all_occurrences(db, today())
        db.commit()
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title="Invoice Keeper",
        description="Напоминания о регулярных платежах: аренда, подписки, серверы.",
        version="0.1.0",
        docs_url=f"{API_PREFIX}/docs",
        openapi_url=f"{API_PREFIX}/openapi.json",
        redoc_url=None,
        lifespan=lifespan,
    )

    api = APIRouter(prefix=API_PREFIX)

    @api.get("/health", tags=["system"], summary="Проверка работоспособности")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    api.include_router(auth.router)

    app.include_router(api)
    return app


app = create_app()
