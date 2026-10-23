import logging
from typing import Protocol

import httpx

from app.core.config import Settings

logger = logging.getLogger("invoice_keeper")


class TelegramError(Exception):
    """Сообщение не доставлено. В тексте ошибки токена бота нет и быть не должно."""


class Notifier(Protocol):
    """Канал напоминаний. Telegram сейчас единственный, email и webhook встанут рядом."""

    @property
    def configured(self) -> bool: ...

    def send(self, text: str) -> None: ...


class TelegramNotifier:
    def __init__(self, settings: Settings, transport: httpx.BaseTransport | None = None) -> None:
        self._token = settings.telegram_bot_token.strip()
        self._chat_id = settings.telegram_chat_id.strip()
        self._base = settings.telegram_api_base.rstrip("/")
        self._transport = transport

    @property
    def configured(self) -> bool:
        return bool(self._token and self._chat_id)

    def send(self, text: str) -> None:
        if not self.configured:
            raise TelegramError("Telegram не настроен: нужны TELEGRAM_BOT_TOKEN и TELEGRAM_CHAT_ID")

        url = f"{self._base}/bot{self._token}/sendMessage"
        payload = {"chat_id": self._chat_id, "text": text, "disable_web_page_preview": True}
        try:
            with httpx.Client(transport=self._transport, timeout=10.0) as client:
                response = client.post(url, json=payload)
        except httpx.HTTPError as error:
            # str(error) может содержать URL с токеном, поэтому берём только тип ошибки
            raise TelegramError(f"сеть недоступна ({type(error).__name__})") from None

        try:
            body = response.json()
        except ValueError:
            raise TelegramError(f"Telegram вернул не JSON, код {response.status_code}") from None

        if response.status_code != 200 or not body.get("ok"):
            description = str(body.get("description", "без описания"))
            raise TelegramError(f"Telegram отклонил сообщение: {description} (код {response.status_code})")


def build_notifier(settings: Settings) -> Notifier:
    return TelegramNotifier(settings)
