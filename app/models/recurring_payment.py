from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Integer, String, func
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
    # Ответственный: обычный пользователь, ему лично уходят напоминания по этому платежу
    assignee_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))

    assignee: Mapped["User | None"] = relationship(lazy="selectin")
    pauses: Mapped[list["PaymentPause"]] = relationship(
        order_by="PaymentPause.paused_from", lazy="selectin", cascade="all, delete-orphan", passive_deletes=True
    )
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

    def is_paused_on(self, day: date) -> bool:
        """Срок попадает в паузу: такой период не создаётся и не напоминает."""
        return any(pause.covers(day) for pause in self.pauses)

    def open_pause(self, today: date) -> "PaymentPause | None":
        """Действующая сейчас или бессрочная пауза, которую можно продлить или снять."""
        return next((p for p in self.pauses if p.paused_until is None or p.paused_until > today), None)

    @property
    def assignee_login(self) -> str | None:
        return self.assignee.login if self.assignee is not None else None

    @property
    def is_active(self) -> bool:
        return self.deleted_at is None

    @property
    def currency_enum(self) -> Currency:
        return Currency(self.currency)
