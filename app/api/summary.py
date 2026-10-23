from datetime import date
from typing import Annotated

from fastapi import APIRouter, Query

from app.api.deps import CurrentPrincipal, DbDep, TodayDep
from app.schemas.payments import CurrencySummaryOut, SummaryOut
from app.schemas.planning import (
    BudgetLineOut,
    BudgetMonthOut,
    BudgetOut,
    CalendarDayOut,
    CalendarItemOut,
    CalendarOut,
)
from app.services import planning
from app.services.occurrences import CurrencySummary, OccurrenceFilter, overdue_days, summarize

router = APIRouter(prefix="/payments", tags=["summary"])

IncludeDeleted = Annotated[bool, Query(description="Учитывать историю прекращённых платежей")]


def _line(line: planning.BudgetLine) -> BudgetLineOut:
    money = planning.BudgetLine.money
    return BudgetLineOut(
        currency=line.currency,
        planned=money(line.planned_minor),
        paid=money(line.paid_minor),
        remaining=money(line.remaining_minor),
        count_planned=line.count_planned,
        count_paid=line.count_paid,
    )


@router.get(
    "/summary",
    response_model=SummaryOut,
    summary="Итоговые суммы платежей по валютам",
    description=(
        "Суммы считаются отдельно по RUB, USD и EUR, без конвертации. Все три валюты есть всегда.\n\n"
        "Параметр `on` даёт итоги на дату: считаются периоды со сроком не позже этой даты (если не задан `due_to`), "
        "оплата, отмеченная позже `on`, ещё не учитывается, просрочка считается на `on`."
    ),
)
def payments_summary(
    _principal: CurrentPrincipal,
    db: DbDep,
    today: TodayDep,
    due_from: date | None = None,
    due_to: date | None = None,
    on: Annotated[date | None, Query(description="Итоги на эту дату, по умолчанию сегодня")] = None,
    include_deleted: IncludeDeleted = False,
) -> SummaryOut:
    if on is not None and due_to is None:
        due_to = on
    rows = summarize(
        db, OccurrenceFilter(due_from=due_from, due_to=due_to, include_deleted=include_deleted), today, on=on
    )
    money = CurrencySummary.money
    return SummaryOut(
        as_of=on or today,
        currencies=[
            CurrencySummaryOut(
                currency=row.currency,
                total=money(row.total_minor),
                paid=money(row.paid_minor),
                unpaid=money(row.unpaid_minor),
                overdue=money(row.overdue_minor),
                count_total=row.count_total,
                count_paid=row.count_paid,
                count_unpaid=row.count_unpaid,
                count_overdue=row.count_overdue,
            )
            for row in rows
        ],
    )


@router.get(
    "/budget",
    response_model=BudgetOut,
    summary="Бюджет: плановые расходы на месяц или год по валютам",
    description=(
        "Считает плановые расходы по каждой валюте отдельно: будущие периоды вычисляются по правилу повторения, "
        "поэтому бюджет можно строить и на год вперёд. `paid` это уже оплаченное, `remaining` остаток. "
        "С `month` вернётся один месяц, без него год с разбивкой по месяцам."
    ),
)
def payments_budget(
    _principal: CurrentPrincipal,
    db: DbDep,
    today: TodayDep,
    year: Annotated[int | None, Query(ge=2000, le=2100, description="По умолчанию текущий год")] = None,
    month: Annotated[int | None, Query(ge=1, le=12)] = None,
    include_deleted: IncludeDeleted = False,
) -> BudgetOut:
    year = year or today.year
    budget = planning.build_budget(db, year, month, include_deleted)
    return BudgetOut(
        year=year,
        month=month,
        currencies=[_line(line) for line in budget.total.values()],
        months=[
            BudgetMonthOut(month=m, currencies=[_line(line) for line in lines.values()])
            for m, lines in sorted(budget.months.items())
        ]
        or None,
    )


@router.get(
    "/calendar",
    response_model=CalendarOut,
    summary="Календарь оплат на месяц",
    description=(
        "Платежи месяца по дням. `status`: `paid`, `unpaid` или `planned` (период ещё не создан, он вычислен "
        "по правилу повторения). Итоги месяца считаются по валютам отдельно."
    ),
)
def payments_calendar(
    _principal: CurrentPrincipal,
    db: DbDep,
    today: TodayDep,
    year: Annotated[int | None, Query(ge=2000, le=2100)] = None,
    month: Annotated[int | None, Query(ge=1, le=12)] = None,
    include_deleted: IncludeDeleted = False,
) -> CalendarOut:
    year, month = year or today.year, month or today.month
    days, totals = planning.build_calendar(db, year, month, include_deleted)

    def item(period: planning.PlannedPeriod) -> CalendarItemOut:
        occ = period.occurrence
        days_over = overdue_days(occ, today) if occ else 0
        return CalendarItemOut(
            occurrence_id=occ.id if occ else None,
            recurring_id=period.payment.id,
            name=period.payment.name,
            amount=period.payment.amount,
            currency=period.payment.currency,
            due_date=period.due_date,
            status=occ.status if occ else "planned",
            paid_at=occ.paid_at if occ else None,
            is_overdue=days_over > 0,
            overdue_days=days_over,
            payment_deleted=period.payment.deleted_at is not None,
        )

    return CalendarOut(
        year=year,
        month=month,
        today=today,
        days=[CalendarDayOut(day=day, items=[item(p) for p in periods]) for day, periods in sorted(days.items())],
        totals=[_line(line) for line in totals.values()],
    )
