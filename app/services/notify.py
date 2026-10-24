from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Protocol


class NotifyError(Exception):
    """Канал не смог доставить сообщение. В тексте ошибки не должно быть токенов и паролей."""


@dataclass(frozen=True)
class Reminder:
    """Одно напоминание об оплате периода, общее для всех каналов."""

    occurrence_id: int
    payment_id: int
    name: str
    amount: Decimal
    currency: str
    due_date: date
    days_left: int  # отрицательное значение: период уже просрочен
    text: str  # готовый текст для мессенджеров
    overdue_notice: bool = False  # повторное напоминание: срок прошёл, а оплаты нет
    html: str = ""  # то же для мессенджеров с разметкой HTML (статус, жирная сумма); пусто, значит слать text
    pay_url: str | None = None  # куда платить: кнопка «Оплатить» в мессенджерах и письме
    pay_details: str | None = None  # реквизиты, уже вписаны в text и html

    @property
    def is_overdue(self) -> bool:
        return self.days_left < 0


class Notifier(Protocol):
    """Канал напоминаний: Telegram, MAX, email, webhook. Новый канал это класс с этими тремя членами."""

    name: str

    @property
    def configured(self) -> bool: ...

    def send(self, reminder: Reminder) -> None: ...
