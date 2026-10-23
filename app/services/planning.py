import calendar
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Currency, OccurrenceStatus, PaymentOccurrence, RecurringPayment
from app.services.periods import due_date_for


@dataclass(frozen=True)
class PlannedPeriod:
    """Период платежа: уже созданный в базе или только запланированный (occurrence пуст)."""

    payment: RecurringPayment
    due_date: date
    occurrence: PaymentOccurrence | None

    @property
    def is_paid(self) -> bool:
        return self.occurrence is not None and self.occurrence.status == OccurrenceStatus.PAID.value


def projected_due_dates(first_due: date, start: date, end: date) -> Iterator[date]:
    """Сроки ежемесячного платежа в отрезке [start, end], считая от якоря (как и сами периоды)."""
    if end < first_due or end < start:
        return
    k = max(0, (start.year - first_due.year) * 12 + start.month - first_due.month - 1)
    while (due := due_date_for(first_due, k)) <= end:
        if due >= start:
            yield due
        k += 1


def load_periods(db: Session, start: date, end: date, include_deleted: bool = False) -> list[PlannedPeriod]:
    """Все периоды в [start, end]: будущие считаются по правилу повторения, прошлые берутся из базы."""
    existing = {
        (o.recurring_id, o.due_date): o
        for o in db.scalars(
            select(PaymentOccurrence).where(PaymentOccurrence.due_date >= start, PaymentOccurrence.due_date <= end)
        )
    }
    result: list[PlannedPeriod] = []
    for payment in db.scalars(select(RecurringPayment).order_by(RecurringPayment.id)):
        if payment.deleted_at is None:
            for due in projected_due_dates(payment.first_due_date, start, end):
                result.append(PlannedPeriod(payment, due, existing.get((payment.id, due))))
        elif include_deleted:
            # у прекращённого платежа будущее не планируем, остаётся только его история
            result.extend(
                PlannedPeriod(payment, due, occ) for (rid, due), occ in existing.items() if rid == payment.id
            )
    result.sort(key=lambda p: (p.due_date, p.payment.id))
    return result


def month_bounds(year: int, month: int) -> tuple[date, date]:
    return date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1])


@dataclass
class BudgetLine:
    currency: Currency
    planned_minor: int = 0
    paid_minor: int = 0
    count_planned: int = 0
    count_paid: int = 0

    @property
    def remaining_minor(self) -> int:
        return self.planned_minor - self.paid_minor

    @staticmethod
    def money(minor: int) -> Decimal:
        return Decimal(minor).scaleb(-2)


def _empty_lines() -> dict[Currency, BudgetLine]:
    return {currency: BudgetLine(currency) for currency in Currency}


def _add(lines: dict[Currency, BudgetLine], period: PlannedPeriod) -> None:
    line = lines[Currency(period.payment.currency)]
    line.planned_minor += period.payment.amount_minor
    line.count_planned += 1
    if period.is_paid:
        line.paid_minor += period.payment.amount_minor
        line.count_paid += 1


@dataclass
class Budget:
    year: int
    month: int | None
    total: dict[Currency, BudgetLine] = field(default_factory=_empty_lines)
    months: dict[int, dict[Currency, BudgetLine]] = field(default_factory=dict)


def build_budget(db: Session, year: int, month: int | None, include_deleted: bool = False) -> Budget:
    """Плановые расходы по валютам за месяц или за год (с разбивкой по месяцам)."""
    start, end = month_bounds(year, month) if month else (date(year, 1, 1), date(year, 12, 31))
    budget = Budget(year, month)
    if month is None:
        budget.months = {m: _empty_lines() for m in range(1, 13)}
    for period in load_periods(db, start, end, include_deleted):
        _add(budget.total, period)
        if month is None:
            _add(budget.months[period.due_date.month], period)
    return budget


def build_calendar(
    db: Session, year: int, month: int, include_deleted: bool = False
) -> tuple[dict[date, list[PlannedPeriod]], dict[Currency, BudgetLine]]:
    """Периоды месяца по дням и суммы месяца по валютам."""
    start, end = month_bounds(year, month)
    days: dict[date, list[PlannedPeriod]] = {}
    totals = _empty_lines()
    for period in load_periods(db, start, end, include_deleted):
        days.setdefault(period.due_date, []).append(period)
        _add(totals, period)
    return days, totals
