from datetime import UTC, datetime

from fastapi import APIRouter, BackgroundTasks, HTTPException, Response, status
from sqlalchemy import select

from app.api.deps import AdminPrincipal, CurrentPrincipal, DbDep, NotifiersDep, SettingsDep, TodayDep
from app.core.db import SessionLocal
from app.services import audit
from app.models import RecurringPayment
from app.schemas.payments import RecurringPaymentCreate, RecurringPaymentOut
from app.services.periods import ensure_occurrences
from app.services.reminders import run_reminders

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
    payload: RecurringPaymentCreate,
    admin: AdminPrincipal,
    db: DbDep,
    today: TodayDep,
    background: BackgroundTasks,
    notifiers: NotifiersDep,
    settings: SettingsDep,
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
    audit.record(
        db,
        "payment.create",
        audit.actor_of(admin),
        "payment",
        payment.id,
        {
            "name": payment.name,
            "amount": str(payment.amount),
            "currency": payment.currency,
            "first_due_date": payment.first_due_date.isoformat(),
        },
    )
    db.commit()
    # Платёж добавлен меньше чем за 3 дня до срока: напоминание уходит сразу, не дожидаясь планировщика
    background.add_task(run_reminders, SessionLocal, notifiers, settings, today)
    return payment


@router.delete(
    "/{id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Прекращение регулярного платежа (администратор)",
    description="Платёж и его напоминания прекращаются, история периодов сохраняется.",
)
def delete_recurring_payment(id: int, admin: AdminPrincipal, db: DbDep) -> Response:  # noqa: A002
    payment = _get_active(db, id)
    payment.deleted_at = datetime.now(UTC)
    audit.record(db, "payment.delete", audit.actor_of(admin), "payment", payment.id, {"name": payment.name})
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
