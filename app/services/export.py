import csv
import io
from datetime import date
from decimal import Decimal

from app.models import OccurrenceStatus, PaymentOccurrence
from app.services.occurrences import overdue_days

HEADER = [
    "Платёж",
    "Сумма",
    "Валюта",
    "Срок",
    "Статус",
    "Дата оплаты",
    "Просрочка, дней",
    "Периодичность",
    "Платёж прекращён",
    "Чеков и ссылок",
    "Категория",
    "Ответственный",
]
PERIOD_LABELS = {"monthly": "ежемесячно", "quarterly": "раз в квартал", "yearly": "раз в год"}


def _cell(text: str) -> str:
    """Название из базы не должно стать формулой в Excel: =, +, -, @ в начале экранируются."""
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


def _money(amount: Decimal) -> str:
    return f"{amount:.2f}".replace(".", ",")


def _date(value: date | None) -> str:
    return value.strftime("%d.%m.%Y") if value else ""


def occurrences_csv(items: list[PaymentOccurrence], today: date) -> str:
    """CSV для бухгалтерии под русский Excel: разделитель «;», запятая в суммах, BOM для кириллицы."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";", lineterminator="\r\n")
    writer.writerow(HEADER)
    for occurrence in items:
        payment = occurrence.recurring_payment
        writer.writerow(
            [
                _cell(payment.name),
                _money(occurrence.amount),
                payment.currency,
                _date(occurrence.due_date),
                "оплачен" if occurrence.status == OccurrenceStatus.PAID.value else "не оплачен",
                _date(occurrence.paid_at),
                overdue_days(occurrence, today),
                PERIOD_LABELS.get(payment.period, payment.period),
                "да" if payment.deleted_at is not None else "",
                len(occurrence.receipts),
                _cell(payment.category or ""),
                payment.assignee_login or "",
            ]
        )
    return "﻿" + buffer.getvalue()
