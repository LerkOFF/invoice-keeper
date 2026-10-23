from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Response, status
from sqlalchemy import select

from app.api.deps import AdminPrincipal, CurrentPrincipal, DbDep, TodayDep
from app.models import RecurringPayment
from app.schemas.payments import RecurringPaymentCreate, RecurringPaymentOut
from app.services.periods import ensure_occurrences

router = APIRouter(prefix="/recurring-payments", tags=["recurring-payments"])


def _get_active(db, payment_id: int) -> RecurringPayment:
    payment = db.get(RecurringPayment, payment_id)
    if payment is None or payment.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Регулярный платёж не найден")
    return payment


@router.get("", response_model=list[RecurringPaymentOut], summary="Список регулярных платежей")
def list_recurring_payments(
    _principal: CurrentPrincipal, db: DbDep, include_deleted: bool = False
) -> list[RecurringPayment]:
    stmt = select(RecurringPayment).order_by(RecurringPayment.id)
    if not include_deleted:
        stmt = stmt.where(RecurringPayment.deleted_at.is_(None))
    return list(db.scalars(stmt))


@router.post(
    "",
    response_model=RecurringPaymentOut,
    status_code=status.HTTP_201_CREATED,
    summary="Создание регулярного платежа (администратор)",
)
def create_recurring_payment(
    payload: RecurringPaymentCreate, _admin: AdminPrincipal, db: DbDep, today: TodayDep
) -> RecurringPayment:
    payment = RecurringPayment(
        name=payload.name.strip(),
        currency=payload.currency.value,
        first_due_date=payload.first_due_date,
        period=payload.period.value,
    )
    payment.amount = payload.amount
    db.add(payment)
    db.flush()
    ensure_occurrences(db, payment, today)
    db.commit()
    return payment


@router.delete(
    "/{payment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Прекращение регулярного платежа (администратор)",
    description="Платёж и его напоминания прекращаются, история периодов сохраняется.",
)
def delete_recurring_payment(payment_id: int, _admin: AdminPrincipal, db: DbDep) -> Response:
    payment = _get_active(db, payment_id)
    payment.deleted_at = datetime.now(UTC)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
