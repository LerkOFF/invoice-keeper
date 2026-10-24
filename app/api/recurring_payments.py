from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Response, UploadFile, status
from sqlalchemy import select

from app.api.deps import AdminPrincipal, CurrentPrincipal, DbDep, NotifiersDep, SettingsDep, TodayDep
from app.core.db import SessionLocal
from app.services import audit
from app.models import RecurringPayment
from app.schemas.payments import (
    ImportResult,
    ImportRowOut,
    PauseRequest,
    RecurringPaymentCreate,
    RecurringPaymentOut,
    RecurringPaymentUpdate,
)
from app.services import importer
from app.services.payments import (
    EXTRA_FIELDS,
    PaymentRuleError,
    check_assignee,
    pause_payment,
    resume_payment,
    update_payment,
    update_payment_extras,
)
from app.services.periods import ensure_occurrences
from app.services.reminders import run_reminders

router = APIRouter(prefix="/recurring-payments", tags=["recurring-payments"])
CENT = Decimal("0.01")


def _get_active(db, payment_id: int) -> RecurringPaymentOut:
    payment = db.get(RecurringPayment, payment_id)
    if payment is None or payment.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Регулярный платёж не найден")
    return payment


def payment_out(payment: RecurringPayment, today) -> RecurringPaymentOut:  # noqa: ANN001
    """Платёж для ответа: состояние паузы зависит от «сегодня», поэтому собирается здесь, а не в модели."""
    out = RecurringPaymentOut.model_validate(payment)
    pause = payment.open_pause(today) if payment.deleted_at is None else None
    return out.model_copy(
        update={
            "is_paused": payment.deleted_at is None and payment.is_paused_on(today),
            "paused_from": pause.paused_from if pause else None,
            "paused_until": pause.paused_until if pause else None,
        }
    )


@router.get("", response_model=list[RecurringPaymentOut], summary="Список регулярных платежей")
def list_recurring_payments(
    _principal: CurrentPrincipal, db: DbDep, today: TodayDep, include_deleted: bool = False
) -> list[RecurringPaymentOut]:
    stmt = select(RecurringPayment).order_by(RecurringPayment.id)
    if not include_deleted:
        stmt = stmt.where(RecurringPayment.deleted_at.is_(None))
    return [payment_out(payment, today) for payment in db.scalars(stmt)]


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
) -> RecurringPaymentOut:
    try:
        check_assignee(db, payload.assignee_id)
    except PaymentRuleError as error:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)) from error
    payment = RecurringPayment(
        name=payload.name.strip(),
        currency=payload.currency.value,
        first_due_date=payload.first_due_date,
        period=payload.period.value,
        pay_url=payload.pay_url,
        pay_details=payload.pay_details,
        category=payload.category,
        assignee_id=payload.assignee_id,
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
            "assignee": payment.assignee_login,
        },
    )
    db.commit()
    # Платёж добавлен меньше чем за 3 дня до срока: напоминание уходит сразу, не дожидаясь планировщика
    background.add_task(run_reminders, SessionLocal, notifiers, settings, today)
    return payment_out(payment, today)


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
) -> RecurringPaymentOut:
    if not payload.model_fields_set:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Нужно передать хотя бы одно поле")
    payment = _get_active(db, id)
    try:
        if "assignee_id" in payload.model_fields_set:
            check_assignee(db, payload.assignee_id)
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
    return payment_out(payment, today)


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


@router.post(
    "/{id}/pause",
    response_model=RecurringPaymentOut,
    summary="Пауза платежа (администратор)",
    description=(
        "С сегодняшнего дня до `until` (не включая) или до возобновления: новые периоды не создаются, напоминаний нет. "
        "Неоплаченные периоды внутри паузы без чеков убираются, оплаченные и прошлые долги остаются. "
        "Повторный вызов меняет дату окончания действующей паузы."
    ),
    responses={404: {"description": "Платёж не найден или прекращён"}, 422: {"description": "Дата окончания не позже сегодня"}},
)
def pause_recurring_payment(
    id: int, payload: PauseRequest, admin: AdminPrincipal, db: DbDep, today: TodayDep  # noqa: A002
) -> RecurringPaymentOut:
    payment = _get_active(db, id)
    try:
        pause_payment(db, payment, today, payload.until)
    except PaymentRuleError as error:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)) from error
    audit.record(
        db, "payment.pause", audit.actor_of(admin), "payment", payment.id,
        {"name": payment.name, "until": payload.until.isoformat() if payload.until else None},
    )
    db.commit()
    return payment_out(payment, today)


@router.post(
    "/{id}/resume",
    response_model=RecurringPaymentOut,
    summary="Снятие паузы (администратор)",
    description="Сроки с сегодняшнего дня снова создаются и напоминают. Пропущенные на паузе месяцы просрочкой не становятся.",
    responses={404: {"description": "Платёж не найден или прекращён"}, 422: {"description": "Платёж не на паузе"}},
)
def resume_recurring_payment(
    id: int,  # noqa: A002
    admin: AdminPrincipal,
    db: DbDep,
    today: TodayDep,
    background: BackgroundTasks,
    notifiers: NotifiersDep,
    settings: SettingsDep,
) -> RecurringPaymentOut:
    payment = _get_active(db, id)
    try:
        resume_payment(db, payment, today)
    except PaymentRuleError as error:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)) from error
    audit.record(db, "payment.resume", audit.actor_of(admin), "payment", payment.id, {"name": payment.name})
    db.commit()
    # возобновлённый платёж мог сразу оказаться в окне трёх дней
    background.add_task(run_reminders, SessionLocal, notifiers, settings, today)
    return payment_out(payment, today)


@router.get(
    "/import/template",
    response_class=Response,
    summary="Шаблон CSV для импорта (администратор)",
    responses={200: {"content": {"text/csv": {}}, "description": "CSV с заголовками и тремя примерами"}},
)
def import_template(_admin: AdminPrincipal) -> Response:
    return Response(
        content=importer.template_csv(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="invoice-keeper-import.csv"'},
    )


@router.post(
    "/import",
    response_model=ImportResult,
    summary="Импорт регулярных платежей из CSV (администратор)",
    description=(
        "Столбцы как в шаблоне: Название, Сумма, Валюта, Первый срок (обязательные), Периодичность, Категория, "
        "Ответственный, Ссылка на оплату, Реквизиты. Разделитель «;», «,» или табуляция, суммы с запятой или точкой, "
        "даты ДД.ММ.ГГГГ или ГГГГ-ММ-ДД. `dry_run=true` (по умолчанию) только проверяет и показывает ошибки по строкам; "
        "`dry_run=false` создаёт платежи, только если ошибок нет ни в одной строке. До 500 строк и 1 МБ."
    ),
    responses={422: {"description": "Файл не читается или в строках есть ошибки"}},
)
def import_payments(
    file: UploadFile,
    admin: AdminPrincipal,
    db: DbDep,
    today: TodayDep,
    background: BackgroundTasks,
    notifiers: NotifiersDep,
    settings: SettingsDep,
    dry_run: Annotated[bool, Query(description="Только проверить, ничего не создавать")] = True,
) -> ImportResult:
    try:
        rows = importer.parse(db, file.file.read(importer.MAX_BYTES + 1))
    except importer.ImportFileError as error:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)) from error

    out = [
        ImportRowOut(
            line=row.line,
            name=row.payload.name if row.payload else row.values.get("name"),
            amount=row.payload.amount.quantize(CENT) if row.payload else None,
            currency=row.payload.currency if row.payload else None,
            first_due_date=row.payload.first_due_date if row.payload else None,
            period=row.payload.period if row.payload else None,
            category=row.payload.category if row.payload else None,
            assignee_login=row.assignee_login,
            pay_url=row.payload.pay_url if row.payload else None,
            errors=row.errors,
            warnings=row.warnings,
        )
        for row in rows
    ]
    valid = sum(1 for row in rows if not row.errors)
    if dry_run:
        return ImportResult(dry_run=True, valid=valid, created=0, rows=out)
    if valid != len(rows):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="В файле есть строки с ошибками: исправьте их и загрузите снова, ничего не создано",
        )

    for row in rows:
        payload = row.payload
        payment = RecurringPayment(
            name=payload.name.strip(),
            currency=payload.currency.value,
            first_due_date=payload.first_due_date,
            period=payload.period.value,
            pay_url=payload.pay_url,
            pay_details=payload.pay_details,
            category=payload.category,
            assignee_id=payload.assignee_id,
        )
        payment.amount = payload.amount
        db.add(payment)
        db.flush()
        ensure_occurrences(db, payment, today)
    audit.record(
        db,
        "payment.import",
        audit.actor_of(admin),
        details={"count": len(rows), "file": (file.filename or "")[:100], "names": [r.payload.name for r in rows[:20]]},
    )
    db.commit()
    background.add_task(run_reminders, SessionLocal, notifiers, settings, today)
    return ImportResult(dry_run=False, valid=valid, created=len(rows), rows=out)
