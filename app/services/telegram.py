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
        if not self._token:
            raise TelegramError("Telegram не настроен: нужен TELEGRAM_BOT_TOKEN")

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
        if reminder.html:
            self.send_text(reminder.html, pay_button_for=reminder.occurrence_id, html=True, pay_url=reminder.pay_url)
        else:
            self.send_text(reminder.text, pay_button_for=reminder.occurrence_id, pay_url=reminder.pay_url)

    def send_text(
        self, text: str, *, pay_button_for: int | None = None, html: bool = False, pay_url: str | None = None
    ) -> None:
        payload: dict[str, Any] = {"chat_id": self.chat_id, "text": text, "disable_web_page_preview": True}
        if html:
            payload["parse_mode"] = "HTML"
        paid_button = pay_button_for if self._settings.telegram_buttons_enabled else None
        if markup := pay_keyboard(paid_button, pay_url):
            payload["reply_markup"] = markup
        self.call("sendMessage", payload)


def pay_keyboard(occurrence_id: int | None, pay_url: str | None = None) -> dict[str, Any] | None:
    """Кнопка «Оплачено» (если включена) и ссылка «Оплатить» (если у платежа есть). Ни того, ни другого: None."""
    rows: list[list[dict[str, str]]] = []
    if occurrence_id is not None:
        rows.append([{"text": "✅ Оплачено", "callback_data": f"{PAY_CALLBACK_PREFIX}{occurrence_id}"}])
    if pay_url:
        rows.append([{"text": "💳 Оплатить", "url": pay_url}])
    return {"inline_keyboard": rows} if rows else None


def build_notifier(settings: Settings) -> Notifier:
    return TelegramNotifier(settings)


def build_notifiers(settings: Settings) -> list[Notifier]:
    """Все каналы напоминаний. Ненастроенные остаются в списке и пропускаются при отправке."""
    from app.services.mailer import EmailNotifier
    from app.services.max_api import MaxNotifier
    from app.services.webhook import WebhookNotifier

    return [TelegramNotifier(settings), MaxNotifier(settings), EmailNotifier(settings), WebhookNotifier(settings)]
