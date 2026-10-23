from datetime import date
from typing import Annotated

from fastapi import APIRouter, Query

from app.api.deps import CurrentPrincipal, DbDep, TodayDep
from app.schemas.payments import CurrencySummaryOut, SummaryOut
from app.services.occurrences import CurrencySummary, OccurrenceFilter, summarize

router = APIRouter(prefix="/payments", tags=["summary"])


@router.get(
    "/summary",
    response_model=SummaryOut,
    summary="Итоговые суммы платежей по валютам",
    description="Суммы считаются отдельно по RUB, USD и EUR, без конвертации. Все три валюты есть всегда.",
)
def payments_summary(
    _principal: CurrentPrincipal,
    db: DbDep,
    today: TodayDep,
    due_from: date | None = None,
    due_to: date | None = None,
    include_deleted: Annotated[bool, Query(description="Учитывать историю прекращённых платежей")] = False,
) -> SummaryOut:
    rows = summarize(
        db, OccurrenceFilter(due_from=due_from, due_to=due_to, include_deleted=include_deleted), today
    )
    money = CurrencySummary.money
    return SummaryOut(
        as_of=today,
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
