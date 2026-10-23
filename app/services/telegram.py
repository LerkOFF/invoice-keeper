import logging
from typing import Any

import httpx

from app.core.config import Settings
from app.services.notify import Notifier, NotifyError, Reminder

logger = logging.getLogger("invoice_keeper")

PAY_CALLBACK_PREFIX = "paid:"


class TelegramError(NotifyError):
    """Запрос к Telegram не удался. В тексте ошибки токена бота нет и быть не должно."""


class TelegramApi:
    """Тонкая обёртка над Bot API: один метод call, ошибки без токена."""

    def __init__(self, settings: Settings, transport: httpx.BaseTransport | None = None) -> None:
        self._settings = settings
        self._token = settings.telegram_bot_token.strip()
        self.chat_id = settings.telegram_chat_id.strip()
        self._base = settings.telegram_api_base.rstrip("/")
        self._transport = transport

    @property
    def configured(self) -> bool:
        return bool(self._token and self.chat_id)

    def call(self, method: str, payload: dict[str, Any] | None = None, *, timeout: float = 10.0) -> Any:
        """Вызывает метод Bot API и возвращает поле result."""
        if not self.configured:
            raise TelegramError("Telegram не настроен: нужны TELEGRAM_BOT_TOKEN и TELEGRAM_CHAT_ID")

        url = f"{self._base}/bot{self._token}/{method}"
        try:
            with httpx.Client(transport=self._transport, timeout=timeout) as client:
                response = client.post(url, json=payload or {})
        except httpx.HTTPError as error:
            # str(error) может содержать URL с токеном, поэтому берём только тип ошибки
            raise TelegramError(f"сеть недоступна ({type(error).__name__})") from None

        try:
            body = response.json()
        except ValueError:
            raise TelegramError(f"Telegram вернул не JSON, код {response.status_code}") from None

        if response.status_code != 200 or not body.get("ok"):
            description = str(body.get("description", "без описания"))
            raise TelegramError(f"Telegram отклонил запрос {method}: {description} (код {response.status_code})")
        return body.get("result")


class TelegramNotifier(TelegramApi):
    name = "telegram"

    def send(self, reminder: Reminder) -> None:
        self.send_text(reminder.text, pay_button_for=reminder.occurrence_id)

    def send_text(self, text: str, *, pay_button_for: int | None = None) -> None:
        payload: dict[str, Any] = {"chat_id": self.chat_id, "text": text, "disable_web_page_preview": True}
        if pay_button_for is not None and self._settings.telegram_buttons_enabled:
            payload["reply_markup"] = pay_keyboard(pay_button_for)
        self.call("sendMessage", payload)


def pay_keyboard(occurrence_id: int) -> dict[str, Any]:
    return {"inline_keyboard": [[{"text": "✅ Оплачено", "callback_data": f"{PAY_CALLBACK_PREFIX}{occurrence_id}"}]]}


def build_notifier(settings: Settings) -> Notifier:
    return TelegramNotifier(settings)


def build_notifiers(settings: Settings) -> list[Notifier]:
    """Все каналы напоминаний. Ненастроенные остаются в списке и пропускаются при отправке."""
    from app.services.webhook import WebhookNotifier

    return [TelegramNotifier(settings), WebhookNotifier(settings)]
