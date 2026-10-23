import calendar
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import PaymentOccurrence, Period, RecurringPayment


def due_date_for(anchor: date, months_after: int) -> date:
    """Срок периода через `months_after` месяцев после якоря.

    Число месяца берётся из якоря, а не из предыдущего периода: если такого дня
    в месяце нет, срок падает на последний день (31 янв -> 28 фев -> 31 мар).
    """
    year, month0 = divmod(anchor.year * 12 + anchor.month - 1 + months_after, 12)
    month = month0 + 1
    day = min(anchor.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def period_due_date(anchor: date, period: Period | str, index: int) -> date:
    """Срок периода номер `index` (с нуля): ежемесячно шаг 1 месяц, раз в квартал 3, раз в год 12."""
    return due_date_for(anchor, index * Period(period).months)


def ensure_occurrences(db: Session, payment: RecurringPayment, today: date) -> list[PaymentOccurrence]:
    """Догенерирует периоды платежа до горизонта «сегодня плюс месяц».

    Ближайший предстоящий период создаётся всегда, даже если он дальше горизонта
    (годовой платёж через полгода): так всегда видно, что и когда платить.
    Прошлые периоды не трогаются, просрочка не останавливает следующие.
    Возвращает только созданные периоды. Коммит остаётся за вызывающим.
    """
    if not payment.is_active:
        return []

    horizon = due_date_for(today, 1)
    existing = set(
        db.scalars(
            select(PaymentOccurrence.due_date).where(PaymentOccurrence.recurring_id == payment.id)
        )
    )

    created: list[PaymentOccurrence] = []
    index = 0
    upcoming_seen = False
    while True:
        due = period_due_date(payment.first_due_date, payment.period, index)
        if due > horizon and upcoming_seen:
            break
        if due not in existing:
            occurrence = PaymentOccurrence(recurring_payment=payment, due_date=due, amount_minor=payment.amount_minor)
            db.add(occurrence)
            created.append(occurrence)
        upcoming_seen = upcoming_seen or due >= today
        index += 1
    return created


def ensure_all_occurrences(db: Session, today: date) -> int:
    """Прогоняет генерацию по всем активным платежам, вернёт число новых периодов."""
    payments = db.scalars(select(RecurringPayment).where(RecurringPayment.deleted_at.is_(None)))
    return sum(len(ensure_occurrences(db, payment, today)) for payment in payments)
