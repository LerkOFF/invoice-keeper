import calendar
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import PaymentOccurrence, RecurringPayment


def due_date_for(anchor: date, months_after: int) -> date:
    """Срок периода через `months_after` месяцев после якоря.

    Число месяца берётся из якоря, а не из предыдущего периода: если такого дня
    в месяце нет, срок падает на последний день (31 янв -> 28 фев -> 31 мар).
    """
    year, month0 = divmod(anchor.year * 12 + anchor.month - 1 + months_after, 12)
    month = month0 + 1
    day = min(anchor.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def ensure_occurrences(db: Session, payment: RecurringPayment, today: date) -> list[PaymentOccurrence]:
    """Догенерирует периоды платежа до горизонта «сегодня плюс месяц».

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
    months = 0
    while (due := due_date_for(payment.first_due_date, months)) <= horizon:
        if due not in existing:
            occurrence = PaymentOccurrence(recurring_payment=payment, due_date=due)
            db.add(occurrence)
            created.append(occurrence)
        months += 1
    return created


def ensure_all_occurrences(db: Session, today: date) -> int:
    """Прогоняет генерацию по всем активным платежам, вернёт число новых периодов."""
    payments = db.scalars(select(RecurringPayment).where(RecurringPayment.deleted_at.is_(None)))
    return sum(len(ensure_occurrences(db, payment, today)) for payment in payments)
