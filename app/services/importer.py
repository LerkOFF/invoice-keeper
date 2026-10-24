import csv
import io
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import RecurringPayment, Role, User
from app.schemas.payments import RecurringPaymentCreate

MAX_ROWS = 500
MAX_BYTES = 1_000_000

# Заголовок столбца (в нижнем регистре) → поле. Русские названия как в выгрузке, английские как в API
COLUMNS = {
    "название": "name", "платёж": "name", "платеж": "name", "name": "name",
    "сумма": "amount", "amount": "amount",
    "валюта": "currency", "currency": "currency",
    "первый срок": "first_due_date", "срок": "first_due_date", "дата ближайшей оплаты": "first_due_date",
    "first_due_date": "first_due_date",
    "периодичность": "period", "period": "period",
    "категория": "category", "category": "category",
    "ответственный": "assignee", "assignee": "assignee",
    "ссылка на оплату": "pay_url", "pay_url": "pay_url",
    "реквизиты": "pay_details", "pay_details": "pay_details",
}
REQUIRED = ("name", "amount", "currency", "first_due_date")
PERIODS = {
    "": "monthly", "ежемесячно": "monthly", "каждый месяц": "monthly", "monthly": "monthly",
    "раз в квартал": "quarterly", "ежеквартально": "quarterly", "quarterly": "quarterly",
    "раз в год": "yearly", "ежегодно": "yearly", "yearly": "yearly",
}
CURRENCIES = {"rub": "RUB", "руб": "RUB", "₽": "RUB", "usd": "USD", "$": "USD", "eur": "EUR", "€": "EUR"}

TEMPLATE_ROWS = [
    ["Название", "Сумма", "Валюта", "Первый срок", "Периодичность", "Категория", "Ответственный", "Ссылка на оплату", "Реквизиты"],
    ["Аренда офиса", "45000,00", "RUB", "18.11.2026", "ежемесячно", "Аренда", "", "", "Договор 42"],
    ["Сервер Aeza", "20", "USD", "25.11.2026", "ежемесячно", "IT", "", "https://my.aeza.ru", ""],
    ["Продление домена", "1290", "RUB", "07.12.2026", "раз в год", "IT", "", "", ""],
]


class ImportFileError(Exception):
    """Файл целиком не читается: роутер превращает это в 422."""


@dataclass
class ImportRow:
    line: int
    values: dict = field(default_factory=dict)
    payload: RecurringPaymentCreate | None = None
    assignee_login: str | None = None
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def template_csv() -> str:
    buffer = io.StringIO()
    csv.writer(buffer, delimiter=";", lineterminator="\r\n").writerows(TEMPLATE_ROWS)
    return "﻿" + buffer.getvalue()


def _decode(raw: bytes) -> str:
    if len(raw) > MAX_BYTES:
        raise ImportFileError("Файл больше 1 МБ")
    for encoding in ("utf-8-sig", "cp1251"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ImportFileError("Не получилось прочитать файл: сохраните его в UTF-8")


def _delimiter(head: str) -> str:
    counts = {d: head.count(d) for d in (";", ",", "\t")}
    return max(counts, key=counts.get) if any(counts.values()) else ";"


def _amount(value: str) -> Decimal:
    text = re.sub(r"[\s ₽$€]", "", value).replace(",", ".")
    try:
        return Decimal(text)
    except InvalidOperation:
        raise ValueError(f"сумма «{value}» не число") from None


def _date(value: str) -> date:
    for fmt in ("%d.%m.%Y", "%Y-%m-%d", "%d.%m.%y", "%d/%m/%Y"):
        try:
            return datetime.strptime(value.strip(), fmt).date()
        except ValueError:
            continue
    raise ValueError(f"дата «{value}» не похожа на ДД.ММ.ГГГГ")


_NAMES = {"name": "название", "amount": "сумма", "currency": "валюта", "pay_url": "ссылка на оплату",
          "pay_details": "реквизиты", "category": "категория", "first_due_date": "первый срок"}
_MESSAGES = {
    "string_too_short": "не заполнено",
    "string_too_long": "слишком длинно",
    "greater_than": "должна быть больше нуля",
    "decimal_max_places": "не больше двух знаков после запятой",
    "decimal_max_digits": "слишком большое число",
    "enum": "RUB, USD или EUR",
}


def _pydantic_errors(error: ValidationError) -> list[str]:
    result = []
    for item in error.errors():
        where = _NAMES.get(str(item["loc"][-1]), str(item["loc"][-1])) if item.get("loc") else ""
        message = _MESSAGES.get(item.get("type", ""), str(item.get("msg", "")).removeprefix("Value error, "))
        result.append(f"{where}: {message}" if where else message)
    return result


def parse(db: Session, raw: bytes) -> list[ImportRow]:
    """Разбирает CSV и проверяет каждую строку теми же правилами, что и создание платежа в API."""
    text = _decode(raw)
    lines = text.splitlines()
    if not lines or not lines[0].strip():
        raise ImportFileError("Файл пустой")
    reader = csv.reader(io.StringIO(text), delimiter=_delimiter(lines[0]))
    header = [COLUMNS.get(h.strip().lower()) for h in next(reader)]
    missing = [col for col in REQUIRED if col not in header]
    if missing:
        raise ImportFileError(
            "Нет обязательных столбцов: " + ", ".join(missing) + ". Возьмите заголовки из шаблона"
        )

    users = {u.login.lower(): u for u in db.scalars(select(User).where(User.role == Role.USER.value))}
    existing = {(p.name.lower(), p.currency) for p in db.scalars(select(RecurringPayment).where(RecurringPayment.deleted_at.is_(None)))}
    seen: dict[tuple[str, str], int] = {}
    rows: list[ImportRow] = []
    for number, cells in enumerate(reader, start=2):
        if not any(c.strip() for c in cells):
            continue
        if len(rows) >= MAX_ROWS:
            raise ImportFileError(f"Больше {MAX_ROWS} строк: разбейте файл на части")
        values = {col: cells[i].strip() for i, col in enumerate(header) if col and i < len(cells)}
        row = ImportRow(line=number, values=values)
        data: dict = {"name": values.get("name", ""), "category": values.get("category") or None,
                      "pay_url": values.get("pay_url") or None, "pay_details": values.get("pay_details") or None}
        try:
            data["amount"] = _amount(values.get("amount", ""))
        except ValueError as error:
            row.errors.append(str(error))
        currency = values.get("currency", "").strip()
        data["currency"] = CURRENCIES.get(currency.lower(), currency.upper())
        if data["currency"] not in CURRENCIES.values():
            row.errors.append(f"валюта «{currency}»: RUB, USD или EUR")
        try:
            data["first_due_date"] = _date(values.get("first_due_date", ""))
        except ValueError as error:
            row.errors.append(str(error))
        period = PERIODS.get(values.get("period", "").strip().lower())
        if period is None:
            row.errors.append(f"периодичность «{values.get('period')}»: ежемесячно, раз в квартал или раз в год")
        data["period"] = period or "monthly"
        login = values.get("assignee", "").lstrip("@").strip()
        if login:
            user = users.get(login.lower())
            if user is None:
                row.errors.append(f"ответственный «{login}»: такого пользователя нет")
            else:
                data["assignee_id"], row.assignee_login = user.id, user.login
        if not row.errors:
            try:
                row.payload = RecurringPaymentCreate(**data)
            except ValidationError as error:
                row.errors.extend(_pydantic_errors(error))
        if row.payload:
            key = (row.payload.name.strip().lower(), row.payload.currency.value)
            if key in existing:
                row.warnings.append("платёж с таким названием и валютой уже есть")
            if key in seen:
                row.warnings.append(f"повторяет строку {seen[key]}")
            seen.setdefault(key, number)
        rows.append(row)
    if not rows:
        raise ImportFileError("В файле нет строк с платежами")
    return rows
