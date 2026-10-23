import asyncio
import contextlib
import logging
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI

from app.api import auth, payment_occurrences, recurring_payments, summary, users
from app.core.clock import today
from app.core.config import get_settings
from app.core.db import SessionLocal, init_db
from app.scheduler import scheduler_loop, tick
from app.seed import seed_demo_data
from app.services.telegram import build_notifier
from app.services.periods import ensure_all_occurrences

API_PREFIX = "/api/v1"

logger = logging.getLogger("invoice_keeper")
if not logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logger.addHandler(_handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False


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

    notifier = build_notifier(settings)
    if not notifier.configured:
        logger.warning("TELEGRAM_BOT_TOKEN или TELEGRAM_CHAT_ID не заданы: напоминания не будут отправляться")

    task = None
    if settings.scheduler_enabled:

        def job() -> None:
            tick(SessionLocal, notifier, settings, today())

        task = asyncio.create_task(scheduler_loop(job, settings.scheduler_interval_seconds))

    yield

    if task is not None:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


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
    api.include_router(recurring_payments.router)
    api.include_router(payment_occurrences.router)
    api.include_router(summary.router)
    api.include_router(users.router)

    app.include_router(api)
    return app


app = create_app()
