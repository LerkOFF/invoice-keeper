from datetime import date
from decimal import Decimal
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StringConstraints

from app.models import Currency, OccurrenceStatus, Period
from app.schemas.common import UtcDateTime

Money = Annotated[Decimal, Field(gt=0, max_digits=12, decimal_places=2, examples=["45000.00"])]


def _http_url(value: str | None) -> str | None:
    """Ссылка на оплату: только http(s), без пробелов и кавычек. Пустая строка значит «нет ссылки»."""
    value = (value or "").strip()
    if not value:
        return None
    if not value.lower().startswith(("https://", "http://")) or any(c in value for c in " <>\"\'\n\r\t"):
        raise ValueError("ссылка должна начинаться с http:// или https:// и не содержать пробелов")
    return value


def _details(value: str | None) -> str | None:
    value = (value or "").strip()
    return value or None


PayUrl = Annotated[
    str | None,
    Field(max_length=500, description="Ссылка на оплату: личный кабинет, счёт, страница оплаты", examples=["https://my.aeza.ru"]),
    AfterValidator(_http_url),
]
def _category(value: str | None) -> str | None:
    """Категория: лишние пробелы убираются, пустая строка значит «без категории»."""
    value = " ".join((value or "").split())
    return value or None


Category = Annotated[
    str | None,
    Field(max_length=60, description="Категория платежа для фильтра и бюджета", examples=["Аренда"]),
    AfterValidator(_category),
]
PayDetails = Annotated[
    str | None,
    Field(max_length=1000, description="Реквизиты или подсказка, как платить", examples=["Счёт по договору 42, ИНН 7700000000"]),
    AfterValidator(_details),
]
# пробелы по краям отрезаются до проверки длины: название из одних пробелов не пройдёт
PaymentName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]


class RecurringPaymentCreate(BaseModel):
    name: PaymentName = Field(examples=["Аренда офиса"])
    amount: Money
    currency: Currency
    first_due_date: date = Field(description="Дата ближайшей оплаты, от неё считаются все периоды")
    pay_url: PayUrl = None
    pay_details: PayDetails = None
    category: Category = None
    period: Period = Field(
        default=Period.MONTHLY,
        description="monthly (каждый месяц), quarterly (раз в квартал), yearly (раз в год). Сроки считаются от первой даты",
    )


class RecurringPaymentUpdate(BaseModel):
    """Правка платежа. Валюта не меняется: у истории оплат своя валюта, для другой заведите новый платёж."""

    model_config = ConfigDict(extra="forbid")

    name: PaymentName | None = None
    amount: Money | None = Field(
        default=None,
        description="Новая сумма для неоплаченных периодов с сегодняшнего дня и всех следующих. Прошлые и оплаченные сохраняют свою",
    )
    period: Period | None = Field(default=None, description="Новая периодичность, вместе с first_due_date")
    first_due_date: date | None = Field(
        default=None,
        description="Дата ближайшей оплаты по новому графику, не раньше сегодня. Нужна, если меняется график",
    )
    pay_url: PayUrl = Field(default=None, description="Новая ссылка на оплату; null или пустая строка убирают её")
    pay_details: PayDetails = Field(default=None, description="Новые реквизиты; null или пустая строка убирают их")
    category: Category = Field(default=None, description="Новая категория; null или пустая строка убирают её")


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
    pay_url: str | None = Field(default=None, description="Ссылка на оплату")
    pay_details: str | None = Field(default=None, description="Реквизиты")
    category: str | None = Field(default=None, description="Категория")


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
    pay_url: str | None = Field(default=None, description="Ссылка на оплату платежа")
    pay_details: str | None = Field(default=None, description="Реквизиты платежа")
    category: str | None = Field(default=None, description="Категория платежа")


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
    overdue: Decimal = Field(description="Неоплаченные периоды после срока (долг)")
    paid_late: Decimal = Field(
        description="Оплаченные позже срока. Вместе с overdue это те же периоды, что в списке с overdue=true"
    )
    count_total: int
    count_paid: int
    count_unpaid: int
    count_overdue: int
    count_paid_late: int


class SummaryOut(BaseModel):
    as_of: date = Field(description="Дата, на которую считается просрочка")
    currencies: list[CurrencySummaryOut]
