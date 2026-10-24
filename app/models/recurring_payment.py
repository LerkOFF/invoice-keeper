from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, Date, DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.enums import Currency, Period


class RecurringPayment(Base):
    """Регулярный платёж. Удаляется мягко, история периодов остаётся."""

    __tablename__ = "recurring_payments"
    __table_args__ = (
        CheckConstraint("amount_minor > 0", name="ck_recurring_amount_positive"),
        CheckConstraint("currency IN ('RUB', 'USD', 'EUR')", name="ck_recurring_currency"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    # Сумма в минорных единицах (копейки, центы): без ошибок округления
    amount_minor: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(3))
    first_due_date: Mapped[date] = mapped_column(Date)
    period: Mapped[str] = mapped_column(String(16), default=Period.MONTHLY.value)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Куда платить: ссылка на кабинет или счёт и реквизиты, попадают в напоминания
    pay_url: Mapped[str | None] = mapped_column(String(500))
    pay_details: Mapped[str | None] = mapped_column(String(1000))
    # Категория для фильтра и бюджета: «Аренда», «IT», «Подписки»
    category: Mapped[str | None] = mapped_column(String(60))

    occurrences: Mapped[list["PaymentOccurrence"]] = relationship(
        back_populates="recurring_payment",
        order_by="PaymentOccurrence.due_date",
        cascade="all, delete-orphan",
    )

    @property
    def amount(self) -> Decimal:
        return Decimal(self.amount_minor).scaleb(-2)

    @amount.setter
    def amount(self, value: Decimal | int | str) -> None:
        self.amount_minor = int((Decimal(value) * 100).to_integral_value())

    @property
    def is_active(self) -> bool:
        return self.deleted_at is None

    @property
    def currency_enum(self) -> Currency:
        return Currency(self.currency)
