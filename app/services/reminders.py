import logging
import threading
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session, joinedload

from app.core.config import Settings
from app.models import OccurrenceStatus, PaymentOccurrence, RecurringPayment
from app.services import audit
from app.services.telegram import Notifier, TelegramError

logger = logging.getLogger("invoice_keeper")

# Один процесс, один замок: планировщик и «напоминание сразу» не отправят одно и то же дважды.
_run_lock = threading.Lock()


def _days_phrase(days_left: int) -> str:
    if days_left < 0:
        return f"просрочен на {-days_left} дн."
    if days_left == 0:
        return "сегодня"
    if days_left == 1:
        return "завтра"
    return f"через {days_left} дн."


def format_money(amount, currency: str) -> str:
    """45000.00 RUB -> «45 000.00 RUB»."""
    whole, _, frac = f"{amount:.2f}".partition(".")
    return f"{int(whole):,}".replace(",", " ") + f".{frac} {currency}"


def build_message(occurrence: PaymentOccurrence, today: date) -> str:
    payment = occurrence.recurring_payment
    days_left = (occurrence.due_date - today).days
    return (
        "🔔 Напоминание об оплате\n\n"
        f"Платёж: {payment.name}\n"
        f"Сумма: {format_money(payment.amount, payment.currency)}\n"
        f"Дата оплаты: {occurrence.due_date:%d.%m.%Y} ({_days_phrase(days_left)})"
    )


def _pending(db: Session, today: date, reminder_days: int) -> list[PaymentOccurrence]:
    """Неоплаченные периоды живых платежей, до срока которых осталось не больше reminder_days
    (в том числе уже просроченные), и по которым напоминание ещё не уходило."""
    stmt = (
        select(PaymentOccurrence)
        .join(RecurringPayment, PaymentOccurrence.recurring_id == RecurringPayment.id)
        .options(joinedload(PaymentOccurrence.recurring_payment))
        .where(
            RecurringPayment.deleted_at.is_(None),
            PaymentOccurrence.status == OccurrenceStatus.UNPAID.value,
            PaymentOccurrence.reminded_at.is_(None),
            PaymentOccurrence.due_date <= today + timedelta(days=reminder_days),
        )
        .order_by(PaymentOccurrence.due_date, PaymentOccurrence.id)
    )
    return list(db.scalars(stmt).unique())


def send_due_reminders(db: Session, notifier: Notifier, settings: Settings, today: date) -> int:
    """Отправляет напоминания, возвращает число доставленных.

    Без дублей: `reminded_at` ставится только после успешной отправки и только если
    поле ещё пусто. Сбой Telegram оставляет период нетронутым, его подхватит следующий проход.
    """
    if not notifier.configured:
        logger.warning("Telegram не настроен, напоминания не отправляются")
        return 0

    sent = 0
    with _run_lock:
        for occurrence in _pending(db, today, settings.reminder_days):
            try:
                notifier.send(build_message(occurrence, today), pay_button_for=occurrence.id)
            except TelegramError as error:
                logger.error("Напоминание по периоду %s не ушло: %s", occurrence.id, error)
                break  # Telegram недоступен: не долбим остальные периоды, повторим в следующий проход

            claimed = db.execute(
                update(PaymentOccurrence)
                .where(PaymentOccurrence.id == occurrence.id, PaymentOccurrence.reminded_at.is_(None))
                .values(reminded_at=datetime.now(UTC))
            )
            if claimed.rowcount:
                audit.record(
                    db,
                    "reminder.sent",
                    audit.SYSTEM,
                    "occurrence",
                    occurrence.id,
                    {"name": occurrence.recurring_payment.name, "due_date": occurrence.due_date.isoformat(), "channel": "telegram"},
                )
            db.commit()
            if claimed.rowcount:
                sent += 1
                logger.info("Напоминание отправлено: период %s, срок %s", occurrence.id, occurrence.due_date)
    return sent


def run_reminders(
    session_factory: Callable[[], Session], notifier: Notifier, settings: Settings, today: date
) -> int:
    """Отдельная сессия для фоновых вызовов (планировщик, задача после создания платежа)."""
    with session_factory() as db:
        return send_due_reminders(db, notifier, settings, today)
