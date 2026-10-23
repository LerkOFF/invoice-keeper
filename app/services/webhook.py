import hashlib
import hmac
import json
import logging
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from typing import Any

import httpx
from sqlalchemy import event
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.services.notify import NotifyError, Reminder

logger = logging.getLogger("invoice_keeper")

SIGNATURE_HEADER = "X-Invoice-Keeper-Signature"
RETRY_DELAYS = (1.0, 3.0)  # события журнала: три попытки, напоминания повторяет планировщик

# Для событий журнала: один пул на процесс, чтобы медленный получатель не тормозил запросы
_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="webhook")


def sign(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


class WebhookNotifier:
    """Отправляет JSON на указанный адрес. Поля `text` и `content` позволяют использовать входящие
    webhook-и Slack, Mattermost, Rocket.Chat (text) и Discord (content) без посредников."""

    name = "webhook"

    def __init__(self, settings: Settings, transport: httpx.BaseTransport | None = None) -> None:
        self._settings = settings
        self._transport = transport

    @property
    def configured(self) -> bool:
        return self._settings.webhook_url.strip().lower().startswith(("http://", "https://"))

    def send(self, reminder: Reminder) -> None:
        self.post(
            "reminder.overdue" if reminder.overdue_notice else "reminder.due",
            {
                "occurrence_id": reminder.occurrence_id,
                "payment_id": reminder.payment_id,
                "name": reminder.name,
                "amount": str(reminder.amount),
                "currency": reminder.currency,
                "due_date": reminder.due_date.isoformat(),
                "days_left": reminder.days_left,
                "is_overdue": reminder.is_overdue,
            },
            reminder.text,
        )

    def post(self, event_name: str, data: dict[str, Any], text: str | None = None) -> None:
        if not self.configured:
            raise NotifyError("Webhook не настроен: нужен WEBHOOK_URL с http:// или https://")
        body = json.dumps(
            {
                "event": event_name,
                "sent_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                "text": text or event_name,
                "content": text or event_name,
                "data": data,
            },
            ensure_ascii=False,
        ).encode()
        headers = {
            "Content-Type": "application/json; charset=utf-8",
            "User-Agent": "invoice-keeper-webhook",
            "X-Invoice-Keeper-Event": event_name,
            "X-Invoice-Keeper-Delivery": uuid.uuid4().hex,
        }
        if self._settings.webhook_secret:
            headers[SIGNATURE_HEADER] = sign(self._settings.webhook_secret, body)
        try:
            with httpx.Client(transport=self._transport, timeout=10.0, follow_redirects=False) as client:
                response = client.post(self._settings.webhook_url.strip(), content=body, headers=headers)
        except httpx.HTTPError as error:
            # адрес мог содержать токен в пути, поэтому в текст ошибки идёт только тип
            raise NotifyError(f"webhook недоступен ({type(error).__name__})") from None
        if not 200 <= response.status_code < 300:
            raise NotifyError(f"webhook ответил кодом {response.status_code}")


# ---------- события журнала ----------


def matches(filters: list[str], action: str) -> bool:
    """«payment.» выбирает группу, «occurrence.paid» одно событие."""
    return any(action.startswith(f) if f.endswith(".") else action == f for f in filters)


def _deliver(settings: Settings, payload: dict[str, Any], transport: httpx.BaseTransport | None = None) -> None:
    notifier = WebhookNotifier(settings, transport)
    last: NotifyError | None = None
    for attempt, delay in enumerate((0.0, *RETRY_DELAYS)):
        if delay:
            time.sleep(delay)
        try:
            notifier.post(payload["event"], {k: v for k, v in payload.items() if k not in {"event", "text"}}, payload["text"])
            return
        except NotifyError as error:
            last = error
            logger.warning("Webhook %s, попытка %s не удалась: %s", payload["event"], attempt + 1, error)
    logger.error("Webhook %s не доставлен: %s", payload["event"], last)


def dispatch_events(events: list[dict[str, Any]]) -> None:
    settings = get_settings()
    if not settings.webhook_url.strip():
        return
    filters = settings.webhook_event_filters
    for item in events:
        if matches(filters, item["event"]):
            _executor.submit(_deliver, settings, item)


@event.listens_for(Session, "after_commit")
def _send_events_after_commit(session: Session) -> None:
    """События уходят только после коммита: откат действия не порождает webhook."""
    events = session.info.pop("audit_events", None)
    if events:
        dispatch_events(events)


@event.listens_for(Session, "after_rollback")
def _drop_events_on_rollback(session: Session) -> None:
    session.info.pop("audit_events", None)
