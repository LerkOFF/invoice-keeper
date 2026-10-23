import asyncio
import contextlib
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api import audit, auth, payment_occurrences, receipts, recurring_payments, summary, users
from app.core.clock import today
from app.core.config import get_settings
from app.core.db import SessionLocal, init_db
from app.scheduler import scheduler_loop, tick
from app.seed import seed_demo_data
from app.services import webhook  # noqa: F401  регистрирует отправку событий журнала после коммита
from app.services.telegram import TelegramApi, build_notifiers
from app.services.telegram_bot import bot_loop, build_bot
from app.services.periods import ensure_all_occurrences

API_PREFIX = "/api/v1"
WEB_DIR = Path(__file__).parent / "web"

# Панель целиком своя: ни внешних скриптов, ни шрифтов, ни инлайновых стилей
PANEL_CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
    "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
)

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
    if settings.admin_password == "change-me":
        logger.warning("ADMIN_PASSWORD остался значением по умолчанию, поменяйте его в .env")
    init_db()
    with SessionLocal() as db:
        if settings.seed_demo_data:
            seed_demo_data(db, settings)
        ensure_all_occurrences(db, today())
        db.commit()

    notifiers = build_notifiers(settings)
    active = [n.name for n in notifiers if n.configured]
    if active:
        logger.info("Каналы напоминаний: %s", ", ".join(active))
    else:
        logger.warning("Ни один канал напоминаний не настроен (Telegram, email, webhook): напоминания не будут отправляться")

    task = None
    if settings.scheduler_enabled:

        def job() -> None:
            tick(SessionLocal, notifiers, settings, today())

        task = asyncio.create_task(scheduler_loop(job, settings.scheduler_interval_seconds))

    bot_task = None
    if settings.telegram_buttons_enabled and TelegramApi(settings).configured:
        bot_task = asyncio.create_task(bot_loop(build_bot(settings, SessionLocal)))

    yield

    for background in (task, bot_task):
        if background is not None:
            background.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await background


def create_app() -> FastAPI:
    app = FastAPI(
        title="Invoice Keeper",
        description="Напоминания о регулярных платежах: аренда, подписки, серверы.",
        version="0.1.0",
        docs_url=f"{API_PREFIX}/docs",
        openapi_url=f"{API_PREFIX}/openapi.json",
        redoc_url=None,
        lifespan=lifespan,
        # читаемые operationId в OpenAPI: login, create_user, update_payment_occurrence
        generate_unique_id_function=lambda route: route.name,
        openapi_tags=[
            {"name": "auth", "description": "Вход, текущий пользователь, завершение сессии"},
            {"name": "recurring-payments", "description": "Регулярные платежи (создание и удаление только админ)"},
            {"name": "payment-occurrences", "description": "Периоды платежей: оплата, отмена, правка даты, просрочка"},
            {"name": "summary", "description": "Итоги по валютам без конвертации"},
            {"name": "users", "description": "Обычные пользователи (только админ)"},
            {"name": "receipts", "description": "Чеки и ссылки, прикреплённые к оплате"},
            {"name": "audit", "description": "Журнал авторизации и действий (только админ)"},
            {"name": "system", "description": "Служебное"},
        ],
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
    api.include_router(audit.router)
    api.include_router(receipts.router)

    app.include_router(api)

    @app.middleware("http")
    async def panel_security_headers(request: Request, call_next):
        response = await call_next(request)
        path = request.url.path
        if path == "/" or path.startswith("/static/"):
            response.headers["Content-Security-Policy"] = PANEL_CSP
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["Referrer-Policy"] = "same-origin"
            response.headers["X-Frame-Options"] = "DENY"
        return response

    @app.get("/", include_in_schema=False)
    def panel() -> FileResponse:
        return FileResponse(WEB_DIR / "index.html", headers={"Cache-Control": "no-cache"})

    app.mount("/static", StaticFiles(directory=WEB_DIR / "static"), name="static")
    return app


app = create_app()
