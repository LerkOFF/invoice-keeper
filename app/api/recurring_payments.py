from datetime import UTC, datetime

from fastapi import APIRouter, BackgroundTasks, HTTPException, Response, status
from sqlalchemy import select

from app.api.deps import AdminPrincipal, CurrentPrincipal, DbDep, NotifiersDep, SettingsDep, TodayDep
from app.core.db import SessionLocal
from app.services import audit
from app.models import RecurringPayment
from app.schemas.payments import RecurringPaymentCreate, RecurringPaymentOut, RecurringPaymentUpdate
from app.services.payments import EXTRA_FIELDS, PaymentRuleError, update_payment, update_payment_extras
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
        pay_url=payload.pay_url,
        pay_details=payload.pay_details,
        category=payload.category,
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
            "period": payment.period,
            "category": payment.category,
        },
    )
    db.commit()
    # Платёж добавлен меньше чем за 3 дня до срока: напоминание уходит сразу, не дожидаясь планировщика
    background.add_task(run_reminders, SessionLocal, notifiers, settings, today)
    return payment


@router.patch(
    "/{id}",
    response_model=RecurringPaymentOut,
    summary="Изменение регулярного платежа (администратор)",
    description=(
        "Меняет название, сумму и график. Новая сумма действует для неоплаченных периодов со сроком "
        "с сегодняшнего дня, прошлые и оплаченные периоды сохраняют свою. Новый график задаётся вместе с датой "
        "ближайшей оплаты (не раньше сегодня): неоплаченные будущие периоды старого графика убираются, история остаётся. "
        "Валюту изменить нельзя."
    ),
    responses={404: {"description": "Платёж не найден или прекращён"}, 422: {"description": "Нарушено правило правки"}},
)
def update_recurring_payment(
    id: int,  # noqa: A002
    payload: RecurringPaymentUpdate,
    admin: AdminPrincipal,
    db: DbDep,
    today: TodayDep,
    background: BackgroundTasks,
    notifiers: NotifiersDep,
    settings: SettingsDep,
) -> RecurringPayment:
    if not payload.model_fields_set:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Нужно передать хотя бы одно поле")
    payment = _get_active(db, id)
    try:
        changes = update_payment(
            db,
            payment,
            today,
            name=payload.name,
            amount=payload.amount,
            period=payload.period,
            first_due_date=payload.first_due_date,
        )
    except PaymentRuleError as error:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)) from error
    changes |= update_payment_extras(payment, {f: getattr(payload, f) for f in EXTRA_FIELDS if f in payload.model_fields_set})
    if changes:
        audit.record(
            db,
            "payment.update",
            audit.actor_of(admin),
            "payment",
            payment.id,
            {
                "name": payment.name,
                "amount": str(payment.amount),
                "currency": payment.currency,
                "period": payment.period,
                "first_due_date": payment.first_due_date.isoformat(),
                **changes,
            },
        )
    db.commit()
    # новый график мог поставить срок ближе чем через 3 дня: напоминание сразу, как при создании
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
