from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, File, Form, HTTPException, Response, UploadFile, status
from fastapi.responses import FileResponse

from app.api.deps import CurrentPrincipal, DbDep, SettingsDep
from app.models import OccurrenceReceipt, PaymentOccurrence
from app.schemas.receipts import ReceiptLinkCreate, ReceiptOut
from app.services import audit
from app.services import receipts as receipts_service
from app.services.auth import Principal
from app.services.receipts import ReceiptError

router = APIRouter(tags=["receipts"])

_NOT_FOUND = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Не найдено")


def can_delete(receipt: OccurrenceReceipt, principal: Principal) -> bool:
    """Администратор удаляет любое вложение, пользователь только своё: сверяется id, а не логин."""
    return principal.is_admin or (principal.id is not None and receipt.created_by_user_id == principal.id)


def to_out(receipt: OccurrenceReceipt, principal: Principal) -> ReceiptOut:
    return ReceiptOut(
        id=receipt.id,
        occurrence_id=receipt.occurrence_id,
        kind=receipt.kind,
        title=receipt.title,
        url=receipt.url,
        filename=receipt.filename,
        content_type=receipt.content_type,
        size_bytes=receipt.size_bytes,
        download_url=f"/api/v1/receipts/{receipt.id}/file" if receipt.kind == "file" else None,
        created_at=receipt.created_at,
        created_by=receipt.created_by,
        created_by_type=receipt.created_by_type,
        can_delete=can_delete(receipt, principal),
    )


def _occurrence(db, occurrence_id: int, for_write: bool = False) -> PaymentOccurrence:
    occurrence = db.get(PaymentOccurrence, occurrence_id)
    if occurrence is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Платёж не найден")
    if for_write and occurrence.recurring_payment.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Регулярный платёж прекращён, период изменить нельзя")
    return occurrence


def _raise(error: ReceiptError) -> None:
    raise HTTPException(status_code=error.status_code, detail=str(error)) from error


def _audit(db, action: str, principal, occurrence: PaymentOccurrence, receipt: OccurrenceReceipt) -> None:
    audit.record(
        db,
        action,
        audit.actor_of(principal),
        "receipt",
        receipt.id,
        {
            "name": occurrence.recurring_payment.name,
            "due_date": occurrence.due_date.isoformat(),
            "occurrence_id": occurrence.id,
            "kind": receipt.kind,
            "title": receipt.title,
            "url": receipt.url,
            "filename": receipt.filename,
        },
    )


@router.get(
    "/payment-occurrences/{id}/receipts",
    response_model=list[ReceiptOut],
    summary="Чеки и ссылки периода",
)
def list_receipts(id: int, principal: CurrentPrincipal, db: DbDep) -> list[ReceiptOut]:  # noqa: A002
    return [to_out(r, principal) for r in _occurrence(db, id).receipts]


@router.post(
    "/payment-occurrences/{id}/receipts/link",
    response_model=ReceiptOut,
    status_code=status.HTTP_201_CREATED,
    summary="Прикрепить ссылку к оплате",
    responses={409: {"description": "Платёж прекращён или слишком много вложений"}, 422: {"description": "Некорректная ссылка"}},
)
def add_link(
    id: int, payload: ReceiptLinkCreate, principal: CurrentPrincipal, db: DbDep, settings: SettingsDep  # noqa: A002
) -> ReceiptOut:
    occurrence = _occurrence(db, id, for_write=True)
    try:
        receipt = receipts_service.add_link(
            db, occurrence, settings, payload.url, payload.title, audit.actor_of(principal), principal.id
        )
    except ReceiptError as error:
        _raise(error)
    _audit(db, "receipt.add", principal, occurrence, receipt)
    db.commit()
    return to_out(receipt, principal)


@router.post(
    "/payment-occurrences/{id}/receipts/file",
    response_model=ReceiptOut,
    status_code=status.HTTP_201_CREATED,
    summary="Загрузить чек (PDF, PNG, JPEG, WebP)",
    description="multipart/form-data: поле `file` и необязательное `title`. Тип проверяется по содержимому, размер до `RECEIPT_MAX_MB`.",
    responses={
        409: {"description": "Платёж прекращён или слишком много вложений"},
        413: {"description": "Файл слишком большой"},
        422: {"description": "Недопустимый формат"},
    },
)
async def add_file(
    id: int,  # noqa: A002
    principal: CurrentPrincipal,
    db: DbDep,
    settings: SettingsDep,
    file: Annotated[UploadFile, File(description="PDF, PNG, JPEG или WebP")],
    title: Annotated[str | None, Form(max_length=200)] = None,
) -> ReceiptOut:
    occurrence = _occurrence(db, id, for_write=True)
    limit = settings.receipt_max_mb * 1024 * 1024
    content = await file.read(limit + 1)  # лишнего в память не читаем
    try:
        receipt = receipts_service.add_file(
            db, occurrence, settings, content, file.filename, title, audit.actor_of(principal), principal.id
        )
    except ReceiptError as error:
        _raise(error)
    _audit(db, "receipt.add", principal, occurrence, receipt)
    db.commit()
    return to_out(receipt, principal)


@router.get(
    "/receipts/{id}/file",
    summary="Скачать загруженный чек",
    responses={404: {"description": "Нет такого файла"}},
)
def download_receipt(id: int, _principal: CurrentPrincipal, db: DbDep, settings: SettingsDep) -> FileResponse:  # noqa: A002
    receipt = db.get(OccurrenceReceipt, id)
    path = receipts_service.file_path(settings, receipt) if receipt else None
    if receipt is None or path is None:
        raise _NOT_FOUND
    disposition = f"inline; filename*=UTF-8''{quote(receipt.filename or 'receipt')}"
    return FileResponse(
        path,
        media_type=receipt.content_type,
        headers={"Content-Disposition": disposition, "X-Content-Type-Options": "nosniff", "Cache-Control": "private, no-store"},
    )


@router.delete(
    "/receipts/{id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Удалить чек или ссылку",
    description="Удалить может администратор или тот, кто прикрепил.",
    responses={403: {"description": "Чужое вложение"}},
)
def delete_receipt(id: int, principal: CurrentPrincipal, db: DbDep, settings: SettingsDep) -> Response:  # noqa: A002
    receipt = db.get(OccurrenceReceipt, id)
    if receipt is None:
        raise _NOT_FOUND
    if not can_delete(receipt, principal):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Удалить может администратор или автор вложения")
    occurrence = db.get(PaymentOccurrence, receipt.occurrence_id)
    _audit(db, "receipt.delete", principal, occurrence, receipt)
    receipts_service.remove_file(settings, receipt)
    db.delete(receipt)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
