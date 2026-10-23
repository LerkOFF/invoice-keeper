from datetime import date
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status

from app.api.deps import CurrentPrincipal, DbDep, TodayDep
from app.models import Currency, OccurrenceStatus, PaymentOccurrence
from app.schemas.payments import OccurrenceOut, OccurrenceUpdate
from app.services.occurrences import (
    OccurrenceFilter,
    OccurrenceRuleError,
    apply_update,
    list_occurrences,
    overdue_days,
)

router = APIRouter(prefix="/payment-occurrences", tags=["payment-occurrences"])


def to_out(occurrence: PaymentOccurrence, today: date) -> OccurrenceOut:
    payment = occurrence.recurring_payment
    days = overdue_days(occurrence, today)
    return OccurrenceOut(
        id=occurrence.id,
        recurring_id=occurrence.recurring_id,
        name=payment.name,
        amount=payment.amount,
        currency=Currency(payment.currency),
        due_date=occurrence.due_date,
        status=OccurrenceStatus(occurrence.status),
        paid_at=occurrence.paid_at,
        is_overdue=days > 0,
        overdue_days=days,
        reminded_at=occurrence.reminded_at,
        payment_deleted=payment.deleted_at is not None,
    )


def _get_or_404(db, occurrence_id: int) -> PaymentOccurrence:
    occurrence = db.get(PaymentOccurrence, occurrence_id)
    if occurrence is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Платёж не найден")
    return occurrence


@router.get("", response_model=list[OccurrenceOut], summary="Список платежей: оплаченные и просроченные")
def list_payment_occurrences(
    _principal: CurrentPrincipal,
    db: DbDep,
    today: TodayDep,
    status_filter: Annotated[OccurrenceStatus | None, Query(alias="status")] = None,
    overdue: Annotated[bool | None, Query(description="Только просроченные или только без просрочки")] = None,
    currency: Currency | None = None,
    recurring_id: int | None = None,
    due_from: date | None = None,
    due_to: date | None = None,
    include_deleted: Annotated[bool, Query(description="Показать историю прекращённых платежей")] = False,
    limit: Annotated[int, Query(ge=1, le=1000)] = 500,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[OccurrenceOut]:
    flt = OccurrenceFilter(
        status=status_filter,
        overdue=overdue,
        currency=currency,
        recurring_id=recurring_id,
        due_from=due_from,
        due_to=due_to,
        include_deleted=include_deleted,
    )
    return [to_out(item, today) for item in list_occurrences(db, flt, today, limit, offset)]


@router.get("/{occurrence_id}", response_model=OccurrenceOut, summary="Конкретный платёж")
def get_payment_occurrence(
    occurrence_id: int, _principal: CurrentPrincipal, db: DbDep, today: TodayDep
) -> OccurrenceOut:
    return to_out(_get_or_404(db, occurrence_id), today)


@router.patch(
    "/{occurrence_id}",
    response_model=OccurrenceOut,
    summary="Подтверждение или отмена оплаты, исправление фактической даты",
    description=(
        "Доступно и пользователю, и администратору. Меняет только этот период. "
        "`status=paid` без даты ставит сегодняшнюю, `status=unpaid` очищает дату. "
        "Срок периода не меняется, просрочка пересчитывается по фактической дате."
    ),
    responses={
        409: {"description": "Регулярный платёж прекращён"},
        422: {"description": "Нарушено правило оплаты"},
    },
)
def update_payment_occurrence(
    occurrence_id: int,
    payload: OccurrenceUpdate,
    _principal: CurrentPrincipal,
    db: DbDep,
    today: TodayDep,
) -> OccurrenceOut:
    occurrence = _get_or_404(db, occurrence_id)
    if occurrence.recurring_payment.deleted_at is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Регулярный платёж прекращён, период изменить нельзя"
        )
    try:
        apply_update(
            occurrence,
            today,
            status=payload.status,
            paid_at=payload.paid_at,
            paid_at_given="paid_at" in payload.model_fields_set,
        )
    except OccurrenceRuleError as error:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)) from error
    db.commit()
    return to_out(occurrence, today)
