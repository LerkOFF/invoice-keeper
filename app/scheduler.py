import asyncio
import logging
from collections.abc import Callable
from datetime import date

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.services.periods import ensure_all_occurrences
from app.services.reminders import send_due_reminders
from app.services.notify import Notifier

logger = logging.getLogger("invoice_keeper")


def tick(
    session_factory: Callable[[], Session],
    notifiers: Notifier | list[Notifier],
    settings: Settings,
    today: date,
    hour: int | None = None,
) -> int:
    """Один проход: догенерировать периоды, затем разослать напоминания.

    hour это текущий час в часовом поясе приложения: раньше settings.reminder_hour напоминания ждут,
    периоды при этом создаются. Без hour час не проверяется.
    """
    with session_factory() as db:
        created = ensure_all_occurrences(db, today)
        db.commit()
        if created:
            logger.info("Создано новых периодов: %s", created)
        if hour is not None and hour < settings.reminder_hour:
            return 0
        return send_due_reminders(db, notifiers, settings, today)


async def scheduler_loop(job: Callable[[], object], interval_seconds: float) -> None:
    """Вызывает job сразу и затем раз в interval_seconds. Ошибка прохода не останавливает цикл."""
    while True:
        try:
            await asyncio.to_thread(job)
        except Exception:  # noqa: BLE001 фоновый цикл должен пережить любой сбой
            logger.exception("Проход планировщика завершился ошибкой")
        await asyncio.sleep(interval_seconds)
