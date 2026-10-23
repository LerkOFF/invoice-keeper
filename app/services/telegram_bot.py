import asyncio
import logging
import re
import time
from collections.abc import Callable
from datetime import date
from enum import StrEnum
from typing import Any, Protocol

from sqlalchemy.orm import Session

from app.core.clock import today as today_in_tz
from app.core.config import Settings
from app.models import OccurrenceStatus, PaymentOccurrence
from app.services import audit
from app.services.occurrences import apply_update
from app.services.telegram import PAY_CALLBACK_PREFIX, TelegramApi, TelegramError

logger = logging.getLogger("invoice_keeper")

_CALLBACK_RE = re.compile(rf"{re.escape(PAY_CALLBACK_PREFIX)}(\d+)")
_MEMBER_STATUSES = {"creator", "administrator", "member"}
_NO_BUTTONS = {"inline_keyboard": []}


class BotApi(Protocol):
    chat_id: str

    def call(self, method: str, payload: dict[str, Any] | None = None, *, timeout: float = 10.0) -> Any: ...


class PayResult(StrEnum):
    PAID_NOW = "paid_now"
    ALREADY_PAID = "already_paid"
    GONE = "gone"


class PayButtonBot:
    """Принимает нажатия «Оплачено» из напоминаний.

    Кто может нажимать: только участники чата, в который бот шлёт напоминания
    (проверка через getChatMember, результат кэшируется на минуту). Если задан
    TELEGRAM_ALLOWED_USER_IDS, список сужается до перечисленных id. Любая ошибка проверки
    означает отказ. Кнопки из чужих чатов игнорируются.
    """

    def __init__(
        self,
        api: BotApi,
        settings: Settings,
        session_factory: Callable[[], Session],
        today: Callable[[], date] = today_in_tz,
        cache_ttl: float = 60.0,
    ) -> None:
        self._api = api
        self._settings = settings
        self._session_factory = session_factory
        self._today = today
        self._cache_ttl = cache_ttl
        self._member_cache: dict[int, tuple[float, bool]] = {}

    # ---------- опрос ----------

    def poll_once(self, offset: int | None) -> int | None:
        """Один long-poll запрос. Возвращает offset для следующего."""
        timeout = self._settings.telegram_poll_timeout
        payload: dict[str, Any] = {"timeout": timeout, "allowed_updates": ["callback_query"]}
        if offset is not None:
            payload["offset"] = offset
        updates = self._api.call("getUpdates", payload, timeout=timeout + 10) or []

        for update in updates:
            try:
                self.process_update(update)
            except Exception:  # noqa: BLE001 одно битое обновление не должно останавливать остальные
                logger.exception("Не удалось обработать обновление Telegram %s", update.get("update_id"))
            offset = max(offset or 0, update["update_id"] + 1)
        return offset

    # ---------- обработка нажатия ----------

    def process_update(self, update: dict[str, Any]) -> None:
        query = update.get("callback_query")
        if not query:
            return

        query_id = query["id"]
        match = _CALLBACK_RE.fullmatch(query.get("data") or "")
        message = query.get("message") or {}
        chat = message.get("chat") or {}
        user = query.get("from") or {}

        if not match:
            self._answer(query_id, "Неизвестная кнопка", alert=True)
            return
        if not self._is_our_chat(chat):
            self._answer(query_id, "Эта кнопка из другого чата", alert=True)
            return

        allowed = self._is_authorized(user, chat)
        if allowed is None:
            self._answer(query_id, "Не удалось проверить доступ, попробуйте позже", alert=True)
            return
        if not allowed:
            logger.warning("Отказ в кнопке «Оплачено»: пользователь %s не из списка чата", user.get("id"))
            self._answer(query_id, "Нет доступа: отмечать оплату могут только участники чата", alert=True)
            return

        result, paid_at = self._mark_paid(int(match.group(1)), audit.telegram_actor(user))
        original = message.get("text") or ""
        who = _display_name(user)

        if result is PayResult.PAID_NOW:
            logger.info("Оплата периода %s отмечена из Telegram: %s", match.group(1), who)
            self._answer(query_id, "Оплата отмечена ✅")
            self._finish_message(chat, message, f"{original}\n\n✅ Оплачено {_fmt(paid_at)}, отметил(а): {who}")
        elif result is PayResult.ALREADY_PAID:
            self._answer(query_id, "Уже отмечено как оплаченное")
            self._finish_message(chat, message, f"{original}\n\n✅ Оплачено {_fmt(paid_at)}")
        else:
            self._answer(query_id, "Платёж не найден или прекращён", alert=True)
            self._finish_message(chat, message, f"{original}\n\n⚠️ Платёж прекращён")

    # ---------- авторизация ----------

    def _is_our_chat(self, chat: dict[str, Any]) -> bool:
        configured = self._api.chat_id.strip()
        if not chat:
            return False
        if configured.lstrip("-").isdigit():
            return chat.get("id") == int(configured)
        return configured.lstrip("@").lower() == str(chat.get("username", "")).lower()

    def _is_authorized(self, user: dict[str, Any], chat: dict[str, Any]) -> bool | None:
        """True/False по списку чата, None если проверить не удалось (трактуется как отказ)."""
        user_id = user.get("id")
        if not isinstance(user_id, int):
            return False

        allowed_ids = self._settings.allowed_telegram_ids
        if allowed_ids and user_id not in allowed_ids:
            return False

        # Личный чат с ботом: список чата состоит из одного человека
        if chat.get("type") == "private":
            return user_id == chat.get("id")

        cached = self._member_cache.get(user_id)
        if cached and cached[0] > time.monotonic():
            return cached[1]

        try:
            member = self._api.call("getChatMember", {"chat_id": self._api.chat_id, "user_id": user_id})
        except TelegramError as error:
            logger.error("Проверка участника чата не удалась: %s", error)
            return None

        status = (member or {}).get("status")
        is_member = status in _MEMBER_STATUSES or (status == "restricted" and bool((member or {}).get("is_member")))
        self._member_cache[user_id] = (time.monotonic() + self._cache_ttl, is_member)
        return is_member

    # ---------- действия ----------

    def _mark_paid(self, occurrence_id: int, actor: audit.Actor) -> tuple[PayResult, date | None]:
        with self._session_factory() as db:
            occurrence = db.get(PaymentOccurrence, occurrence_id)
            if occurrence is None or occurrence.recurring_payment.deleted_at is not None:
                return PayResult.GONE, None
            if occurrence.status == OccurrenceStatus.PAID.value:
                return PayResult.ALREADY_PAID, occurrence.paid_at

            # те же правила, что и в API: дата по умолчанию сегодняшняя
            before_status, before_paid_at = occurrence.status, occurrence.paid_at
            apply_update(occurrence, self._today(), OccurrenceStatus.PAID, None, False)
            audit.record_occurrence_change(db, occurrence, before_status, before_paid_at, actor, source="telegram")
            db.commit()
            return PayResult.PAID_NOW, occurrence.paid_at

    def _answer(self, query_id: str, text: str, alert: bool = False) -> None:
        try:
            self._api.call("answerCallbackQuery", {"callback_query_id": query_id, "text": text, "show_alert": alert})
        except TelegramError as error:
            # самая частая причина: запрос слишком старый, пока бот был выключен
            logger.warning("answerCallbackQuery не удался: %s", error)

    def _finish_message(self, chat: dict[str, Any], message: dict[str, Any], text: str) -> None:
        """Заменяет текст сообщения и убирает кнопку, чтобы её нельзя было нажать повторно."""
        try:
            self._api.call(
                "editMessageText",
                {
                    "chat_id": chat.get("id"),
                    "message_id": message.get("message_id"),
                    "text": text,
                    "reply_markup": _NO_BUTTONS,
                    "disable_web_page_preview": True,
                },
            )
        except TelegramError as error:
            logger.warning("Не удалось обновить сообщение в Telegram: %s", error)


def _display_name(user: dict[str, Any]) -> str:
    if user.get("username"):
        return f"@{user['username']}"
    name = " ".join(part for part in (user.get("first_name"), user.get("last_name")) if part)
    return name or f"id {user.get('id')}"


def _fmt(value: date | None) -> str:
    return value.strftime("%d.%m.%Y") if value else "—"


def build_bot(settings: Settings, session_factory: Callable[[], Session]) -> PayButtonBot:
    return PayButtonBot(TelegramApi(settings), settings, session_factory)


async def bot_loop(bot: PayButtonBot) -> None:
    """Опрашивает Telegram, пока приложение работает. Сбои связи не останавливают цикл."""
    offset: int | None = None
    failures = 0
    while True:
        try:
            offset = await asyncio.to_thread(bot.poll_once, offset)
            failures = 0
        except TelegramError as error:
            failures += 1
            hint = ""
            if "Conflict" in str(error):
                hint = " (у бота включён webhook или его опрашивает другой процесс)"
            logger.error("Опрос Telegram не удался: %s%s", error, hint)
            await asyncio.sleep(min(5 * failures, 30))
        except Exception:  # noqa: BLE001
            failures += 1
            logger.exception("Сбой цикла бота")
            await asyncio.sleep(min(5 * failures, 30))
