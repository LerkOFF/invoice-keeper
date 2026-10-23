from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Integer, String, UniqueConstraint
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
    # Сумма периода в минорных единицах: фиксируется при создании, правка платежа не меняет историю
    amount_minor: Mapped[int | None] = mapped_column(Integer)

    recurring_payment: Mapped["RecurringPayment"] = relationship(back_populates="occurrences")
    deliveries: Mapped[list["ReminderDelivery"]] = relationship(
        lazy="selectin", cascade="all, delete-orphan", passive_deletes=True
    )
    receipts: Mapped[list["OccurrenceReceipt"]] = relationship(
        order_by="OccurrenceReceipt.id", lazy="selectin", cascade="all, delete-orphan", passive_deletes=True
    )

    @property
    def due_amount_minor(self) -> int:
        """Сумма к оплате за этот период. Пусто только у периодов из старой базы до миграции."""
        return self.amount_minor if self.amount_minor is not None else self.recurring_payment.amount_minor

    @property
    def amount(self) -> Decimal:
        return Decimal(self.due_amount_minor).scaleb(-2)
