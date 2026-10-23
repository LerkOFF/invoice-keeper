from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

from app.models import Currency


class BudgetLineOut(BaseModel):
    currency: Currency
    planned: Decimal = Field(description="Плановые расходы: все периоды выборки, включая будущие", examples=["45000.00"])
    paid: Decimal = Field(description="Из них уже оплачено")
    remaining: Decimal = Field(description="Осталось оплатить: planned минус paid")
    count_planned: int
    count_paid: int


class BudgetMonthOut(BaseModel):
    month: int = Field(ge=1, le=12)
    currencies: list[BudgetLineOut]


class BudgetOut(BaseModel):
    year: int
    month: int | None = Field(description="Пусто, если бюджет считается на год")
    currencies: list[BudgetLineOut] = Field(description="Итог за выбранный месяц или за год, всегда все три валюты")
    months: list[BudgetMonthOut] | None = Field(default=None, description="Разбивка по месяцам, только для года")


class CalendarItemOut(BaseModel):
    occurrence_id: int | None = Field(description="Пусто у запланированного периода, которого в базе ещё нет")
    recurring_id: int
    name: str
    amount: Decimal
    currency: Currency
    due_date: date
    status: Literal["paid", "unpaid", "planned"]
    paid_at: date | None
    is_overdue: bool
    overdue_days: int
    payment_deleted: bool


class CalendarDayOut(BaseModel):
    day: date
    items: list[CalendarItemOut]


class CalendarOut(BaseModel):
    year: int
    month: int
    today: date = Field(description="«Сегодня» по часовому поясу сервера")
    days: list[CalendarDayOut] = Field(description="Только дни, в которые есть платежи")
    totals: list[BudgetLineOut] = Field(description="Итоги месяца по валютам")
