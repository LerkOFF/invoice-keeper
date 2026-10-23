from datetime import date, datetime

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.enums import OccurrenceStatus


class PaymentOccurrence(Base):
    """Один период регулярного платежа со своей датой и отметкой оплаты."""

    __tablename__ = "payment_occurrences"
    __table_args__ = (
        UniqueConstraint("recurring_id", "due_date", name="uq_occurrence_recurring_due"),
        CheckConstraint("status IN ('paid', 'unpaid')", name="ck_occurrence_status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    recurring_id: Mapped[int] = mapped_column(
        ForeignKey("recurring_payments.id", ondelete="CASCADE"), index=True
    )
    due_date: Mapped[date] = mapped_column(Date, index=True)
    status: Mapped[str] = mapped_column(String(8), default=OccurrenceStatus.UNPAID.value)
    paid_at: Mapped[date | None] = mapped_column(Date)
    reminded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    recurring_payment: Mapped["RecurringPayment"] = relationship(back_populates="occurrences")
