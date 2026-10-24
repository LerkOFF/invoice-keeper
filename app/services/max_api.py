import logging
import ssl
from functools import lru_cache
from pathlib import Path
from typing import Any

import certifi
import httpx

from app.core.config import Settings, get_settings
from app.services.notify import NotifyError, Reminder
from app.services.telegram import PAY_CALLBACK_PREFIX

logger = logging.getLogger("invoice_keeper")

# API MAX подписан сертификатом Минцифры, которого нет в certifi
RUSSIAN_CA = Path(__file__).resolve().parent.parent / "certs" / "russian_trusted_ca.pem"


class MaxError(NotifyError):
    """Запрос к MAX не удался. В тексте ошибки токена бота нет и быть не должно."""


@lru_cache
def tls_context() -> ssl.SSLContext:
    context = ssl.create_default_context(cafile=certifi.where())
    context.load_verify_locations(cafile=str(RUSSIAN_CA))
    return context


class MaxApi:
    """Тонкая обёртка над Bot API MAX: один метод call, токен в заголовке Authorization, ошибки без токена."""

    def __init__(self, settings: Settings, transport: httpx.BaseTransport | None = None) -> None:
        self._settings = settings
        self._token = settings.max_bot_token.strip()
        self.chat_id = settings.max_chat_id.strip()
        self._base = settings.max_api_base.rstrip("/")
        self._transport = transport

    @property
    def configured(self) -> bool:
        return bool(self._token and self.chat_id)

    def chat_id_number(self) -> int:
        try:
            return int(self.chat_id)
        except ValueError:
            raise MaxError("MAX_CHAT_ID должен быть числом, например -71234567890123") from None

    def call(
        self,
        http_method: str,
        path: str,
        *,
        query: dict[str, Any] | None = None,
        body: dict[str, Any] | None = None,
        timeout: float = 10.0,
    ) -> Any:
        """Вызывает метод Bot API и возвращает тело ответа."""
        if not self._token:
            raise MaxError("MAX не настроен: нужны MAX_BOT_TOKEN и MAX_CHAT_ID")

        params = {key: value for key, value in (query or {}).items() if value is not None}
        try:
            with httpx.Client(transport=self._transport, timeout=timeout, verify=tls_context()) as client:
                response = client.request(
                    http_method, f"{self._base}{path}", params=params, json=body, headers={"Authorization": self._token}
                )
        except httpx.HTTPError as error:
            raise MaxError(f"сеть недоступна ({type(error).__name__})") from None

        try:
            data = response.json()
        except ValueError:
            raise MaxError(f"MAX вернул не JSON, код {response.status_code}") from None

        failed = isinstance(data, dict) and data.get("success") is False
        if response.status_code != 200 or failed:
            description = "без описания"
            if isinstance(data, dict):
                description = str(data.get("message") or data.get("code") or description)
            raise MaxError(f"MAX отклонил запрос {http_method} {path}: {description} (код {response.status_code})")
        return data


class MaxNotifier(MaxApi):
    name = "max"

    def send(self, reminder: Reminder) -> None:
        if reminder.html:
            self.send_text(reminder.html, pay_button_for=reminder.occurrence_id, html=True, pay_url=reminder.pay_url)
        else:
            self.send_text(reminder.text, pay_button_for=reminder.occurrence_id, pay_url=reminder.pay_url)

    def send_text(
        self, text: str, *, pay_button_for: int | None = None, html: bool = False, pay_url: str | None = None
    ) -> None:
        body: dict[str, Any] = {"text": text}
        if html:
            body["format"] = "html"
        paid_button = pay_button_for if self._settings.max_buttons_enabled else None
        if keyboard := pay_keyboard(paid_button, pay_url):
            body["attachments"] = [keyboard]
        query = {"chat_id": self.chat_id_number(), "disable_link_preview": "true"}
        self.call("POST", "/messages", query=query, body=body)


def pay_keyboard(occurrence_id: int | None, pay_url: str | None = None) -> dict[str, Any] | None:
    """Кнопка «Оплачено» (если включена) и ссылка «Оплатить» (если у платежа есть). Ни того, ни другого: None."""
    rows: list[list[dict[str, str]]] = []
    if occurrence_id is not None:
        rows.append([{"type": "callback", "text": "✅ Оплачено", "payload": f"{PAY_CALLBACK_PREFIX}{occurrence_id}"}])
    if pay_url:
        rows.append([{"type": "link", "text": "💳 Оплатить", "url": pay_url}])
    return {"type": "inline_keyboard", "payload": {"buttons": rows}} if rows else None


def discover_chats(api: MaxApi, timeout: int = 0) -> list[dict[str, Any]]:
    """Чаты из свежих событий бота (добавили в группу, нажали «Начать», написали): отсюда берётся MAX_CHAT_ID.

    Готового списка чатов бота в API MAX нет, id приходит только в событиях.
    """
    query = {"types": "bot_added,bot_started,message_created", "timeout": timeout}
    found: dict[int, dict[str, Any]] = {}
    for update in (api.call("GET", "/updates", query=query, timeout=timeout + 10) or {}).get("updates") or []:
        recipient = (update.get("message") or {}).get("recipient") or {}
        chat_id = update.get("chat_id") or recipient.get("chat_id")
        if chat_id is None:
            continue
        chat_type = recipient.get("chat_type") or ("dialog" if update.get("update_type") == "bot_started" else "chat")
        user = update.get("user") or (update.get("message") or {}).get("sender") or {}
        found[chat_id] = {"chat_id": chat_id, "type": chat_type, "event": update.get("update_type"), "user": user.get("first_name")}
    return list(found.values())


if __name__ == "__main__":
    # docker compose exec app python -m app.services.max_api
    # Сначала добавьте бота в группу администратором (или нажмите «Начать» в диалоге) и напишите там сообщение.
    chats = discover_chats(MaxApi(get_settings()), timeout=5)
    for chat in chats:
        print(f"MAX_CHAT_ID={chat['chat_id']}\t{chat['type']}\t{chat['event']}\t{chat['user'] or ''}")
    if not chats:
        print("Событий нет: добавьте бота в чат администратором, напишите там сообщение и запустите снова")
