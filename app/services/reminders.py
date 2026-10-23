import logging
import threading
from collections.abc import Callable, Iterable
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session, joinedload

from app.core.config import Settings
from app.models import OccurrenceStatus, PaymentOccurrence, RecurringPayment, ReminderDelivery
from app.services import audit
from app.services.notify import Notifier, NotifyError, Reminder

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
        f"Сумма: {format_money(occurrence.amount, payment.currency)}\n"
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


def build_reminder(occurrence: PaymentOccurrence, today: date) -> Reminder:
    payment = occurrence.recurring_payment
    return Reminder(
        occurrence_id=occurrence.id,
        payment_id=payment.id,
        name=payment.name,
        amount=occurrence.amount,
        currency=payment.currency,
        due_date=occurrence.due_date,
        days_left=(occurrence.due_date - today).days,
        text=build_message(occurrence, today),
    )


def as_list(notifiers: Notifier | Iterable[Notifier]) -> list[Notifier]:
    return list(notifiers) if isinstance(notifiers, (list, tuple)) else [notifiers]  # type: ignore[list-item]


def send_due_reminders(
    db: Session, notifiers: Notifier | Iterable[Notifier], settings: Settings, today: date, personal: bool = True
) -> int:
    """Отправляет напоминания по всем настроенным каналам, возвращает число периодов с новыми доставками.

    Без дублей: каждая доставка записывается в `reminder_deliveries` (период + канал, уникально),
    поэтому сбой одного канала не повторяет отправку в другие. `reminded_at` ставится, когда период
    доставлен по всем настроенным каналам. Упавший канал пропускается до конца прохода,
    его период остаётся в очереди и повторяется в следующий раз.

    Личные напоминания: каждый привязанный к пользователю аккаунт Telegram или MAX это отдельный канал
    (`telegram:u5`, `max:admin`), поэтому каждому человеку напоминание приходит один раз. Если человек
    заблокировал бота, его канал считается закрытым для этого периода, чтобы не повторять попытки бесконечно.
    """
    channels = [n for n in as_list(notifiers) if n.configured]
    if personal:
        from app.services.links import is_permanent, personal_notifiers

        channels += [n for n in personal_notifiers(db, settings) if n.configured]
    else:
        def is_permanent(_error: Exception) -> bool:  # noqa: E306
            return False
    if not channels:
        logger.warning("Ни один канал напоминаний не настроен, напоминания не отправляются")
        return 0

    sent = 0
    down: set[str] = set()
    with _run_lock:
        for occurrence in _pending(db, today, settings.reminder_days):
            # свежий запрос, а не occurrence.deliveries: сессия могла пережить прошлый проход
            delivered = set(
                db.scalars(select(ReminderDelivery.channel).where(ReminderDelivery.occurrence_id == occurrence.id))
            )
            reminder = build_reminder(occurrence, today)
            progressed = False

            for channel in channels:
                if channel.name in delivered or channel.name in down:
                    continue
                try:
                    channel.send(reminder)
                except NotifyError as error:
                    logger.error("Напоминание по периоду %s не ушло (%s): %s", occurrence.id, channel.name, error)
                    if ":" in channel.name and is_permanent(error):
                        # личный чат закрыт навсегда (бот заблокирован): больше не пытаемся для этого периода
                        occurrence.deliveries.append(ReminderDelivery(channel=channel.name))
                        delivered.add(channel.name)
                        continue
                    down.add(channel.name)  # канал недоступен: не долбим его остальными периодами
                    continue
                occurrence.deliveries.append(ReminderDelivery(channel=channel.name))
                delivered.add(channel.name)
                progressed = True
                audit.record(
                    db,
                    "reminder.sent",
                    audit.SYSTEM,
                    "occurrence",
                    occurrence.id,
                    {"name": reminder.name, "due_date": occurrence.due_date.isoformat(), "channel": channel.name},
                )
                logger.info("Напоминание отправлено (%s): период %s, срок %s", channel.name, occurrence.id, occurrence.due_date)

            if all(c.name in delivered for c in channels):
                db.execute(
                    update(PaymentOccurrence)
                    .where(PaymentOccurrence.id == occurrence.id, PaymentOccurrence.reminded_at.is_(None))
                    .values(reminded_at=datetime.now(UTC))
                )
            db.commit()
            if progressed:
                sent += 1
    return sent


def run_reminders(
    session_factory: Callable[[], Session],
    notifiers: Notifier | Iterable[Notifier],
    settings: Settings,
    today: date,
) -> int:
    """Отдельная сессия для фоновых вызовов (планировщик, задача после создания платежа)."""
    with session_factory() as db:
        return send_due_reminders(db, notifiers, settings, today)
