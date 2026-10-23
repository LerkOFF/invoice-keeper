from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


def _utcnow() -> datetime:
    return datetime.now(UTC)


class AuditEntry(Base):
    """Запись журнала: кто, что и когда сделал. Только добавляется, не правится и не удаляется."""

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, index=True)
    actor_type: Mapped[str] = mapped_column(String(16))  # admin, user, telegram, system, anonymous
    actor: Mapped[str] = mapped_column(String(100))
    action: Mapped[str] = mapped_column(String(48), index=True)
    target_type: Mapped[str | None] = mapped_column(String(32))
    target_id: Mapped[int | None] = mapped_column(Integer)
    details: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    ip: Mapped[str | None] = mapped_column(String(45))
