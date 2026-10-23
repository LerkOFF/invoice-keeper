from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI

from app.core.clock import today
from app.core.config import get_settings
from app.core.db import SessionLocal, init_db
from app.seed import seed_demo_data
from app.services.periods import ensure_all_occurrences

API_PREFIX = "/api/v1"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    settings = get_settings()
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

    app.include_router(api)
    return app


app = create_app()
