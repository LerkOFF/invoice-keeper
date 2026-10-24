import logging
import threading
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select, update
from sqlalchemy.orm import InstrumentedAttribute, Session, joinedload

from app.core.config import Settings
from app.models import OccurrenceStatus, OverdueDelivery, PaymentOccurrence, RecurringPayment, ReminderDelivery
from app.services import audit, wording
from app.services.notify import Notifier, NotifyError, Reminder

logger = logging.getLogger("invoice_keeper")

# Один процесс, один замок: планировщик и «напоминание сразу» не отправят одно и то же дважды.
_run_lock = threading.Lock()


def _days_phrase(days_left: int) -> str:
    return wording.days_phrase(days_left)


format_money = wording.format_money


def _money(occurrence: PaymentOccurrence) -> str:
    return format_money(occurrence.amount, occurrence.recurring_payment.currency)


def build_message(occurrence: PaymentOccurrence, today: date, html: bool = False) -> str:
    """Напоминание о сроке. Обычный текст для webhook, html=True для Telegram и MAX."""
    return wording.reminder_message(
        occurrence.recurring_payment.name,
        _money(occurrence),
        occurrence.due_date,
        (occurrence.due_date - today).days,
        html=html,
        details=occurrence.recurring_payment.pay_details,
    )


def build_overdue_message(occurrence: PaymentOccurrence, today: date, html: bool = False) -> str:
    return wording.reminder_message(
        occurrence.recurring_payment.name,
        _money(occurrence),
        occurrence.due_date,
        (occurrence.due_date - today).days,
        overdue_notice=True,
        html=html,
        details=occurrence.recurring_payment.pay_details,
    )


@dataclass(frozen=True)
class _Kind:
    """Вид напоминания: где учитывать доставки, чем отмечать «отправлено везде», как писать в журнал."""

    delivery: type
    marker: InstrumentedAttribute
    action: str
    label: str


DUE = _Kind(ReminderDelivery, PaymentOccurrence.reminded_at, "reminder.sent", "Напоминание")
OVERDUE = _Kind(OverdueDelivery, PaymentOccurrence.overdue_reminded_at, "reminder.overdue_sent", "Напоминание о просрочке")


def _local_date(moment: datetime, timezone: str) -> date:
    # SQLite возвращает время без пояса, в базу мы всегда пишем UTC
    aware = moment if moment.tzinfo else moment.replace(tzinfo=UTC)
    return aware.astimezone(ZoneInfo(timezone)).date()


def _pending_overdue(db: Session, today: date, timezone: str) -> list[PaymentOccurrence]:
    """Неоплаченные периоды, срок которых прошёл, а первое напоминание уходило ещё до срока.

    Если первое напоминание само пришло уже после срока (платёж добавили просроченным),
    в нём уже сказано «просрочен», и второе не нужно.
    """
    stmt = (
        select(PaymentOccurrence)
        .join(RecurringPayment, PaymentOccurrence.recurring_id == RecurringPayment.id)
        .options(joinedload(PaymentOccurrence.recurring_payment))
        .where(
            RecurringPayment.deleted_at.is_(None),
            PaymentOccurrence.status == OccurrenceStatus.UNPAID.value,
            PaymentOccurrence.due_date < today,
            PaymentOccurrence.reminded_at.is_not(None),
            PaymentOccurrence.overdue_reminded_at.is_(None),
        )
        .order_by(PaymentOccurrence.due_date, PaymentOccurrence.id)
    )
    return [o for o in db.scalars(stmt).unique() if _local_date(o.reminded_at, timezone) <= o.due_date]


def _pending(db: Session, today: date, reminder_days: int) -> list[PaymentOccurrence]:
    """Неоплаченные периоды живых платежей, до срока которых осталось не больше reminder_days
    (в том числе уже просроченные), и по которым напоминание ещё не уходило.

    Из просроченных берётся только самый свежий период платежа: платёж, внесённый задним числом,
    не должен прислать по сообщению на каждый прошлый месяц. Остальные просрочки видны в панели,
    а следующий из них напомнит о себе, когда свежий оплатят.
    """
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
    occurrences = list(db.scalars(stmt).unique())
    if not any(o.due_date < today for o in occurrences):
        return occurrences
    # самый свежий неоплаченный просроченный период, напоминали по нему или нет
    latest_overdue = dict(
        db.execute(
            select(PaymentOccurrence.recurring_id, func.max(PaymentOccurrence.due_date))
            .where(PaymentOccurrence.status == OccurrenceStatus.UNPAID.value, PaymentOccurrence.due_date < today)
            .group_by(PaymentOccurrence.recurring_id)
        ).all()
    )
    return [o for o in occurrences if o.due_date >= today or latest_overdue.get(o.recurring_id) == o.due_date]


def build_reminder(occurrence: PaymentOccurrence, today: date, overdue_notice: bool = False) -> Reminder:
    payment = occurrence.recurring_payment
    return Reminder(
        occurrence_id=occurrence.id,
        payment_id=payment.id,
        name=payment.name,
        amount=occurrence.amount,
        currency=payment.currency,
        due_date=occurrence.due_date,
        days_left=(occurrence.due_date - today).days,
        text=build_overdue_message(occurrence, today) if overdue_notice else build_message(occurrence, today),
        html=build_overdue_message(occurrence, today, html=True) if overdue_notice else build_message(occurrence, today, html=True),
        overdue_notice=overdue_notice,
        pay_url=payment.pay_url,
        pay_details=payment.pay_details,
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
            reminder = build_reminder(occurrence, today)
            sent += _deliver(db, occurrence, reminder, channels, down, is_permanent, DUE)
        if settings.overdue_reminders:
            for occurrence in _pending_overdue(db, today, settings.app_timezone):
                reminder = build_reminder(occurrence, today, overdue_notice=True)
                sent += _deliver(db, occurrence, reminder, channels, down, is_permanent, OVERDUE)
    return sent


def _deliver(
    db: Session,
    occurrence: PaymentOccurrence,
    reminder: Reminder,
    channels: list[Notifier],
    down: set[str],
    is_permanent: Callable[[Exception], bool],
    kind: _Kind,
) -> int:
    """Рассылает одно напоминание по каналам, где его ещё не было. Вернёт 1, если ушла хоть одна доставка."""
    # свежий запрос, а не связь у периода: сессия могла пережить прошлый проход
    delivered = set(db.scalars(select(kind.delivery.channel).where(kind.delivery.occurrence_id == occurrence.id)))
    progressed = False
    # личный канал может не касаться платежа (у платежа другой ответственный): его пропускаем и не ждём
    channels = [c for c in channels if getattr(c, "applies_to", None) is None or c.applies_to(occurrence.recurring_payment)]

    for channel in channels:
        if channel.name in delivered or channel.name in down:
            continue
        try:
            channel.send(reminder)
        except NotifyError as error:
            logger.error("%s по периоду %s не ушло (%s): %s", kind.label, occurrence.id, channel.name, error)
            if ":" in channel.name and is_permanent(error):
                # личный чат закрыт навсегда (бот заблокирован): больше не пытаемся для этого периода
                db.add(kind.delivery(occurrence_id=occurrence.id, channel=channel.name))
                delivered.add(channel.name)
                continue
            down.add(channel.name)  # канал недоступен: не долбим его остальными периодами
            continue
        db.add(kind.delivery(occurrence_id=occurrence.id, channel=channel.name))
        delivered.add(channel.name)
        progressed = True
        audit.record(
            db,
            kind.action,
            audit.SYSTEM,
            "occurrence",
            occurrence.id,
            {"name": reminder.name, "due_date": occurrence.due_date.isoformat(), "channel": channel.name},
        )
        logger.info("%s отправлено (%s): период %s, срок %s", kind.label, channel.name, occurrence.id, occurrence.due_date)

    if all(c.name in delivered for c in channels):
        db.execute(
            update(PaymentOccurrence)
            .where(PaymentOccurrence.id == occurrence.id, kind.marker.is_(None))
            .values({kind.marker: datetime.now(UTC)})
        )
    db.commit()
    return 1 if progressed else 0


def run_reminders(
    session_factory: Callable[[], Session],
    notifiers: Notifier | Iterable[Notifier],
    settings: Settings,
    today: date,
) -> int:
    """Отдельная сессия для фоновых вызовов (планировщик, задача после создания платежа)."""
    with session_factory() as db:
        return send_due_reminders(db, notifiers, settings, today)
