from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


def _utcnow() -> datetime:
    return datetime.now(UTC)


class ReminderDelivery(Base):
    """Напоминание по периоду, доставленное по конкретному каналу. Не даёт слать в канал дважды."""

    __tablename__ = "reminder_deliveries"
    __table_args__ = (UniqueConstraint("occurrence_id", "channel", name="uq_delivery_occurrence_channel"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    occurrence_id: Mapped[int] = mapped_column(ForeignKey("payment_occurrences.id", ondelete="CASCADE"), index=True)
    channel: Mapped[str] = mapped_column(String(16))
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class OverdueDelivery(Base):
    """Повторное напоминание о просрочке, доставленное по каналу. Одно на период и канал."""

    __tablename__ = "overdue_deliveries"
    __table_args__ = (UniqueConstraint("occurrence_id", "channel", name="uq_overdue_occurrence_channel"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    occurrence_id: Mapped[int] = mapped_column(ForeignKey("payment_occurrences.id", ondelete="CASCADE"), index=True)
    channel: Mapped[str] = mapped_column(String(16))
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
