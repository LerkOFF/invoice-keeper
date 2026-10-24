from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models import OccurrenceStatus, Period, RecurringPayment
from app.services.periods import ensure_occurrences, period_due_date

_UNPAID = OccurrenceStatus.UNPAID.value


class PaymentRuleError(Exception):
    """Нарушено правило правки платежа: роутер превращает это в 422."""


def _to_minor(amount: Decimal) -> int:
    return int((Decimal(amount) * 100).to_integral_value())


def _on_schedule(anchor: date, period: Period, due: date) -> bool:
    index = 0
    while (candidate := period_due_date(anchor, period, index)) <= due:
        if candidate == due:
            return True
        index += 1
    return False


def update_payment(
    db: Session,
    payment: RecurringPayment,
    today: date,
    *,
    name: str | None = None,
    amount: Decimal | None = None,
    period: Period | None = None,
    first_due_date: date | None = None,
) -> dict:
    """Правка регулярного платежа. Возвращает изменения для журнала (пусто, если ничего не поменялось).

    - Название меняется везде, это подпись платежа.
    - Новая сумма действует для неоплаченных периодов со сроком с сегодняшнего дня и для всех следующих.
      Оплаченные и уже просроченные периоды сохраняют свою сумму: история не переписывается.
    - Новый график (периодичность или дата) задаётся датой ближайшей оплаты не раньше сегодня.
      Неоплаченные будущие периоды старого графика убираются (кроме тех, к которым приложены чеки),
      прошлые, оплаченные и просроченные остаются, ближайший период по новому графику создаётся сразу.
    Коммит остаётся за вызывающим.
    """
    changes: dict = {}
    new_period = period or Period(payment.period)
    schedule_changed = new_period.value != payment.period or (
        first_due_date is not None and first_due_date != payment.first_due_date
    )
    if schedule_changed:
        if first_due_date is None:
            raise PaymentRuleError("Новый график: укажите дату ближайшей оплаты")
        if first_due_date < today:
            raise PaymentRuleError("Дата ближайшей оплаты по новому графику не может быть в прошлом")

    if name is not None and name.strip() and name.strip() != payment.name:
        changes["name_before"] = payment.name
        payment.name = name.strip()

    if amount is not None and _to_minor(amount) != payment.amount_minor:
        changes["amount_before"] = str(payment.amount)
        payment.amount_minor = _to_minor(amount)
        for occurrence in payment.occurrences:
            if occurrence.status == _UNPAID and occurrence.due_date >= today:
                occurrence.amount_minor = payment.amount_minor

    if schedule_changed:
        changes["period_before"] = payment.period
        changes["first_due_date_before"] = payment.first_due_date.isoformat()
        payment.period = new_period.value
        payment.first_due_date = first_due_date
        for occurrence in list(payment.occurrences):
            stale = (
                occurrence.status == _UNPAID
                and occurrence.due_date >= today
                and not occurrence.receipts
                and not _on_schedule(first_due_date, new_period, occurrence.due_date)
            )
            if stale:
                payment.occurrences.remove(occurrence)
        db.flush()
        ensure_occurrences(db, payment, today)

    return changes


def update_payment_link(payment: RecurringPayment, fields: dict) -> dict:
    """Ссылка на оплату и реквизиты. В `fields` только переданные поля: None убирает значение."""
    changes: dict = {}
    for field in ("pay_url", "pay_details"):
        if field in fields and fields[field] != getattr(payment, field):
            changes[f"{field}_before"] = getattr(payment, field)
            setattr(payment, field, fields[field])
    return changes
