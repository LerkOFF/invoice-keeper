from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


def _utcnow() -> datetime:
    return datetime.now(UTC)


class OccurrenceReceipt(Base):
    """Чек (файл) или ссылка, прикреплённые к конкретному периоду платежа."""

    __tablename__ = "occurrence_receipts"

    id: Mapped[int] = mapped_column(primary_key=True)
    occurrence_id: Mapped[int] = mapped_column(ForeignKey("payment_occurrences.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(8))  # link или file
    title: Mapped[str | None] = mapped_column(String(200))
    url: Mapped[str | None] = mapped_column(String(2000))
    filename: Mapped[str | None] = mapped_column(String(255))  # имя для показа, на диске файл под другим именем
    stored_name: Mapped[str | None] = mapped_column(String(80))
    content_type: Mapped[str | None] = mapped_column(String(100))
    size_bytes: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    created_by: Mapped[str] = mapped_column(String(100))
    created_by_type: Mapped[str] = mapped_column(String(16))
    # автор из базы; по нему проверяется право удалить. Удалили пользователя: пусто, даже если логин займут снова
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
