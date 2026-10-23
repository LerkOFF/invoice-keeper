from datetime import date
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from app.models import Currency, OccurrenceStatus, Period
from app.schemas.common import UtcDateTime

Money = Annotated[Decimal, Field(gt=0, max_digits=12, decimal_places=2, examples=["45000.00"])]


class RecurringPaymentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200, examples=["Аренда офиса"])
    amount: Money
    currency: Currency
    first_due_date: date = Field(description="Дата ближайшей оплаты, от неё считаются все периоды")
    period: Period = Field(
        default=Period.MONTHLY,
        description="monthly (каждый месяц), quarterly (раз в квартал), yearly (раз в год). Сроки считаются от первой даты",
    )


class RecurringPaymentUpdate(BaseModel):
    """Правка платежа. Валюта не меняется: у истории оплат своя валюта, для другой заведите новый платёж."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=200)
    amount: Money | None = Field(
        default=None,
        description="Новая сумма для неоплаченных периодов с сегодняшнего дня и всех следующих. Прошлые и оплаченные сохраняют свою",
    )
    period: Period | None = Field(default=None, description="Новая периодичность, вместе с first_due_date")
    first_due_date: date | None = Field(
        default=None,
        description="Дата ближайшей оплаты по новому графику, не раньше сегодня. Нужна, если меняется график",
    )


class RecurringPaymentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    amount: Decimal = Field(description="Строка с двумя знаками после точки", examples=["45000.00"])
    currency: Currency
    first_due_date: date
    period: Period
    created_at: UtcDateTime
    deleted_at: UtcDateTime | None = Field(description="Заполнено у прекращённого платежа")


class OccurrenceOut(BaseModel):
    id: int
    recurring_id: int
    name: str
    amount: Decimal = Field(examples=["45000.00"])
    currency: Currency
    due_date: date
    status: OccurrenceStatus
    paid_at: date | None = Field(description="Фактическая дата оплаты")
    is_overdue: bool = Field(description="Не оплачен после срока либо оплачен позже срока")
    overdue_days: int = Field(description="Дней просрочки, 0 если просрочки нет")
    reminded_at: UtcDateTime | None = Field(description="Когда напоминание доставлено по всем настроенным каналам")
    payment_deleted: bool = Field(description="Регулярный платёж прекращён, период остался в истории")
    receipts_count: int = Field(default=0, description="Сколько чеков и ссылок прикреплено к этому периоду")


class OccurrenceUpdate(BaseModel):
    """Подтверждение или отмена оплаты и правка фактической даты."""

    model_config = ConfigDict(extra="forbid")

    status: OccurrenceStatus | None = Field(default=None, description="paid или unpaid")
    paid_at: date | None = Field(
        default=None,
        description="Фактическая дата оплаты. При status=paid без даты ставится сегодняшняя",
    )


class CurrencySummaryOut(BaseModel):
    currency: Currency
    total: Decimal = Field(description="Все периоды выборки")
    paid: Decimal
    unpaid: Decimal
    overdue: Decimal = Field(description="Неоплаченные периоды после срока")
    count_total: int
    count_paid: int
    count_unpaid: int
    count_overdue: int


class SummaryOut(BaseModel):
    as_of: date = Field(description="Дата, на которую считается просрочка")
    currencies: list[CurrencySummaryOut]
