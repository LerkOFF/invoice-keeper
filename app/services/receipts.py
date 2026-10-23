import re
import uuid
from pathlib import Path
from urllib.parse import urlsplit

from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models import OccurrenceReceipt, PaymentOccurrence
from app.services.audit import Actor

# Разрешены только эти форматы: тип определяется по содержимому, а не по имени и заголовку клиента
_SIGNATURES: tuple[tuple[bytes, str, str], ...] = (
    (b"%PDF-", "application/pdf", ".pdf"),
    (b"\x89PNG\r\n\x1a\n", "image/png", ".png"),
    (b"\xff\xd8\xff", "image/jpeg", ".jpg"),
)


class ReceiptError(Exception):
    """Чек или ссылка не приняты, роутер превращает это в 422 (или 413)."""

    def __init__(self, message: str, status_code: int = 422) -> None:
        super().__init__(message)
        self.status_code = status_code


def receipts_dir(settings: Settings) -> Path:
    if settings.receipts_dir:
        return Path(settings.receipts_dir)
    url = make_url(settings.database_url)
    if url.get_backend_name() == "sqlite" and url.database and url.database != ":memory:":
        return Path(url.database).parent / "receipts"
    return Path("data") / "receipts"


def detect_type(content: bytes) -> tuple[str, str] | None:
    for signature, content_type, extension in _SIGNATURES:
        if content.startswith(signature):
            return content_type, extension
    if content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        return "image/webp", ".webp"
    return None


def clean_title(value: str | None) -> str | None:
    value = (value or "").strip()
    return value[:200] or None


def clean_url(value: str) -> str:
    value = value.strip()
    parts = urlsplit(value)
    if parts.scheme not in {"http", "https"} or not parts.netloc or re.search(r"\s", value):
        raise ReceiptError("Ссылка: нужен адрес, начинающийся с http:// или https://")
    if len(value) > 2000:
        raise ReceiptError("Ссылка слишком длинная (до 2000 символов)")
    return value


def _ensure_room(db: Session, occurrence: PaymentOccurrence, settings: Settings) -> None:
    if len(occurrence.receipts) >= settings.receipts_per_period:
        raise ReceiptError(f"К одному периоду можно прикрепить не больше {settings.receipts_per_period} чеков и ссылок", 409)


def add_link(db: Session, occurrence: PaymentOccurrence, settings: Settings, url: str, title: str | None, actor: Actor) -> OccurrenceReceipt:
    _ensure_room(db, occurrence, settings)
    receipt = OccurrenceReceipt(
        occurrence_id=occurrence.id,
        kind="link",
        url=clean_url(url),
        title=clean_title(title),
        created_by=actor.name[:100],
        created_by_type=actor.type,
    )
    db.add(receipt)
    db.flush()
    return receipt


def add_file(
    db: Session,
    occurrence: PaymentOccurrence,
    settings: Settings,
    content: bytes,
    original_name: str | None,
    title: str | None,
    actor: Actor,
) -> OccurrenceReceipt:
    _ensure_room(db, occurrence, settings)
    limit = settings.receipt_max_mb * 1024 * 1024
    if not content:
        raise ReceiptError("Файл пустой")
    if len(content) > limit:
        raise ReceiptError(f"Файл больше {settings.receipt_max_mb} МБ", 413)
    detected = detect_type(content)
    if detected is None:
        raise ReceiptError("Допустимы только PDF, PNG, JPEG и WebP")
    content_type, extension = detected

    directory = receipts_dir(settings)
    directory.mkdir(parents=True, exist_ok=True)
    stored_name = f"{uuid.uuid4().hex}{extension}"
    (directory / stored_name).write_bytes(content)

    shown_name = re.sub(r"[\x00-\x1f/\\]", "_", (original_name or "").strip())[-255:] or f"чек{extension}"
    receipt = OccurrenceReceipt(
        occurrence_id=occurrence.id,
        kind="file",
        title=clean_title(title),
        filename=shown_name,
        stored_name=stored_name,
        content_type=content_type,
        size_bytes=len(content),
        created_by=actor.name[:100],
        created_by_type=actor.type,
    )
    db.add(receipt)
    db.flush()
    return receipt


def file_path(settings: Settings, receipt: OccurrenceReceipt) -> Path | None:
    if receipt.kind != "file" or not receipt.stored_name:
        return None
    path = receipts_dir(settings) / receipt.stored_name
    return path if path.is_file() else None


def remove_file(settings: Settings, receipt: OccurrenceReceipt) -> None:
    path = receipts_dir(settings) / receipt.stored_name if receipt.stored_name else None
    if path is not None:
        path.unlink(missing_ok=True)
