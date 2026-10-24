from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class PaymentPause(Base):
    """Пауза платежа: сроки в [paused_from, paused_until) пропускаются, пустой paused_until — до возобновления.

    Паузы хранятся интервалами, поэтому после возобновления пропущенные месяцы не всплывают просрочкой.
    """

    __tablename__ = "payment_pauses"

    id: Mapped[int] = mapped_column(primary_key=True)
    recurring_id: Mapped[int] = mapped_column(ForeignKey("recurring_payments.id", ondelete="CASCADE"), index=True)
    paused_from: Mapped[date] = mapped_column(Date)
    paused_until: Mapped[date | None] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    def covers(self, day: date) -> bool:
        return self.paused_from <= day and (self.paused_until is None or day < self.paused_until)
