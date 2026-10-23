from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import Select, and_, or_, select
from sqlalchemy.orm import Session, joinedload

from app.models import Currency, OccurrenceStatus, PaymentOccurrence, RecurringPayment

_PAID = OccurrenceStatus.PAID.value
_UNPAID = OccurrenceStatus.UNPAID.value


class OccurrenceRuleError(Exception):
    """Нарушено правило оплаты: роутер превращает это в 422."""


def overdue_days(occurrence: PaymentOccurrence, today: date) -> int:
    """На сколько дней просрочен период, 0 если не просрочен.

    Не оплачен: просрочка со следующего дня после срока.
    Оплачен: просрочка, если фактическая дата позже срока. Оплата в день срока вовремя.
    Срок периода не меняется, поэтому исправление фактической даты пересчитывает результат.
    """
    if occurrence.status == _UNPAID:
        return max((today - occurrence.due_date).days, 0)
    if occurrence.paid_at is not None:
        return max((occurrence.paid_at - occurrence.due_date).days, 0)
    return 0


def _overdue_clause(today: date):
    return or_(
        and_(PaymentOccurrence.status == _UNPAID, PaymentOccurrence.due_date < today),
        and_(
            PaymentOccurrence.status == _PAID,
            PaymentOccurrence.paid_at.is_not(None),
            PaymentOccurrence.paid_at > PaymentOccurrence.due_date,
        ),
    )


@dataclass
class OccurrenceFilter:
    status: OccurrenceStatus | None = None
    overdue: bool | None = None
    currency: Currency | None = None
    recurring_id: int | None = None
    due_from: date | None = None
    due_to: date | None = None
    include_deleted: bool = False


def filtered_statement(stmt: Select, flt: OccurrenceFilter, today: date) -> Select:
    stmt = stmt.join(RecurringPayment, PaymentOccurrence.recurring_id == RecurringPayment.id)
    if not flt.include_deleted:
        stmt = stmt.where(RecurringPayment.deleted_at.is_(None))
    if flt.status is not None:
        stmt = stmt.where(PaymentOccurrence.status == flt.status.value)
    if flt.overdue is True:
        stmt = stmt.where(_overdue_clause(today))
    elif flt.overdue is False:
        stmt = stmt.where(~_overdue_clause(today))
    if flt.currency is not None:
        stmt = stmt.where(RecurringPayment.currency == flt.currency.value)
    if flt.recurring_id is not None:
        stmt = stmt.where(PaymentOccurrence.recurring_id == flt.recurring_id)
    if flt.due_from is not None:
        stmt = stmt.where(PaymentOccurrence.due_date >= flt.due_from)
    if flt.due_to is not None:
        stmt = stmt.where(PaymentOccurrence.due_date <= flt.due_to)
    return stmt


def list_occurrences(
    db: Session, flt: OccurrenceFilter, today: date, limit: int, offset: int
) -> list[PaymentOccurrence]:
    stmt = filtered_statement(
        select(PaymentOccurrence).options(joinedload(PaymentOccurrence.recurring_payment)), flt, today
    )
    stmt = stmt.order_by(PaymentOccurrence.due_date, PaymentOccurrence.id).limit(limit).offset(offset)
    return list(db.scalars(stmt).unique())


def apply_update(
    occurrence: PaymentOccurrence,
    today: date,
    status: OccurrenceStatus | None,
    paid_at: date | None,
    paid_at_given: bool,
) -> None:
    """Подтверждение или отмена оплаты и правка фактической даты.

    - paid: дата берётся из запроса, иначе остаётся прежняя, иначе сегодня;
    - unpaid: дата очищается и передавать её нельзя;
    - только paid_at: допустимо для уже оплаченного периода, очистить дату при этом нельзя;
    - фактическая дата не может быть в будущем.
    """
    if status is None and not paid_at_given:
        raise OccurrenceRuleError("Нужно передать status или paid_at")

    if paid_at is not None and paid_at > today:
        raise OccurrenceRuleError("Фактическая дата оплаты не может быть в будущем")

    new_status = status.value if status is not None else occurrence.status

    if new_status == _UNPAID:
        if status is None:
            raise OccurrenceRuleError("Период не оплачен: сначала отметьте оплату (status=paid)")
        if paid_at is not None:
            raise OccurrenceRuleError("Для неоплаченного периода дата оплаты не указывается")
        occurrence.status = _UNPAID
        occurrence.paid_at = None
        return

    if paid_at_given and paid_at is None:
        raise OccurrenceRuleError("Нельзя очистить дату оплаты у оплаченного периода: отмените оплату")

    occurrence.status = _PAID
    occurrence.paid_at = paid_at or occurrence.paid_at or today


@dataclass
class CurrencySummary:
    currency: Currency
    total_minor: int = 0
    paid_minor: int = 0
    unpaid_minor: int = 0
    overdue_minor: int = 0
    count_total: int = 0
    count_paid: int = 0
    count_unpaid: int = 0
    count_overdue: int = 0

    @staticmethod
    def money(minor: int) -> Decimal:
        return Decimal(minor).scaleb(-2)


def summarize(db: Session, flt: OccurrenceFilter, today: date) -> list[CurrencySummary]:
    """Суммы по валютам. Валюты не конвертируются и не смешиваются."""
    rows = db.execute(
        filtered_statement(
            select(PaymentOccurrence, RecurringPayment.currency, RecurringPayment.amount_minor), flt, today
        )
    )
    result = {currency: CurrencySummary(currency) for currency in Currency}
    for occurrence, currency, amount_minor in rows:
        item = result[Currency(currency)]
        item.total_minor += amount_minor
        item.count_total += 1
        if occurrence.status == _PAID:
            item.paid_minor += amount_minor
            item.count_paid += 1
        else:
            item.unpaid_minor += amount_minor
            item.count_unpaid += 1
            if occurrence.due_date < today:
                item.overdue_minor += amount_minor
                item.count_overdue += 1
    return list(result.values())
