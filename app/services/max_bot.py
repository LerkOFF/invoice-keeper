import logging
import re
import time
from collections.abc import Callable
from datetime import date
from typing import Any, Protocol

from sqlalchemy.orm import Session

from app.core.clock import today as today_in_tz
from app.core.config import Settings
from app.services import audit, bot_commands, links
from app.services.max_api import MaxApi, MaxError
from app.services.telegram import PAY_CALLBACK_PREFIX
from app.services.telegram_bot import PayResult, mark_paid, result_message

logger = logging.getLogger("invoice_keeper")

_CALLBACK_RE = re.compile(rf"{re.escape(PAY_CALLBACK_PREFIX)}(\d+)")


class MaxBotApi(Protocol):
    chat_id: str

    def chat_id_number(self) -> int: ...

    def call(
        self,
        http_method: str,
        path: str,
        *,
        query: dict[str, Any] | None = None,
        body: dict[str, Any] | None = None,
        timeout: float = 10.0,
    ) -> Any: ...


class MaxPayButtonBot:
    """Принимает нажатия «Оплачено» из напоминаний в MAX, по тем же правилам, что и Telegram-бот.

    Нажимать могут только участники чата MAX_CHAT_ID (проверка через GET /chats/{id}/members,
    результат кэшируется на минуту). MAX_ALLOWED_USER_IDS сужает круг. Любая ошибка проверки
    означает отказ. Кнопки из чужих чатов игнорируются.
    """

    def __init__(
        self,
        api: MaxBotApi,
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

    def poll_once(self, marker: int | None) -> int | None:
        """Один long-poll запрос GET /updates. Возвращает marker для следующего."""
        timeout = self._settings.max_poll_timeout
        query = {"timeout": timeout, "types": "message_callback,bot_started,message_created", "marker": marker}
        result = self._api.call("GET", "/updates", query=query, timeout=timeout + 10) or {}

        for update in result.get("updates") or []:
            try:
                self.process_update(update)
            except Exception:  # noqa: BLE001 одно битое обновление не должно останавливать остальные
                logger.exception("Не удалось обработать обновление MAX %s", update.get("timestamp"))
        next_marker = result.get("marker")
        return marker if next_marker is None else next_marker

    # ---------- обработка нажатия ----------

    def process_update(self, update: dict[str, Any]) -> None:
        kind = update.get("update_type")
        if kind == "bot_started":
            self._process_start(update.get("chat_id"), update.get("user") or {}, update.get("payload"))
            return
        if kind == "message_created":
            message = update.get("message") or {}
            recipient = message.get("recipient") or {}
            text = ((message.get("body") or {}).get("text") or "").strip()
            sender = message.get("sender") or {}
            command = bot_commands.parse(text)
            if command is not None and not sender.get("is_bot"):
                self._process_command(recipient, sender, command)
                return
            if recipient.get("chat_type") == "dialog" and text.startswith("/start"):
                parts = text.split(maxsplit=1)
                self._process_start(recipient.get("chat_id"), message.get("sender") or {}, parts[1] if len(parts) > 1 else None)
            return
        if kind != "message_callback":
            return

        callback = update.get("callback") or {}
        callback_id = callback["callback_id"]
        match = _CALLBACK_RE.fullmatch(callback.get("payload") or "")
        message = update.get("message") or {}
        recipient = message.get("recipient") or {}
        user = callback.get("user") or {}

        if not match:
            self._answer(callback_id, "Неизвестная кнопка")
            return
        link = self._linked(user)
        personal = (
            recipient.get("chat_type") == "dialog" and link is not None and link.chat_id == str(recipient.get("chat_id"))
        )
        if not personal and not self._is_our_chat(recipient):
            self._answer(callback_id, "Эта кнопка из другого чата")
            return

        # в личке привязанного пользователя нажимать может только он сам; в общем чате правила прежние
        allowed = True if personal else self._is_authorized(user, recipient)
        if allowed is None:
            self._answer(callback_id, "Не удалось проверить доступ, попробуйте позже")
            return
        if not allowed:
            logger.warning("Отказ в кнопке «Оплачено» в MAX: пользователь %s не из списка чата", user.get("user_id"))
            self._answer(callback_id, "Нет доступа: отмечать оплату могут только участники чата")
            return

        actor = self._actor(user, link)
        result, paid_at = mark_paid(self._session_factory, int(match.group(1)), actor, self._today(), source="max")
        original = (message.get("body") or {}).get("text") or ""

        # ответ на нажатие сразу заменяет текст и убирает кнопку, чтобы её нельзя было нажать повторно
        occurrence_id = int(match.group(1))
        who = actor.name if result is PayResult.PAID_NOW else None
        new_text = result_message(self._session_factory, occurrence_id, result, paid_at, who, original)
        if result is PayResult.PAID_NOW:
            logger.info("Оплата периода %s отмечена из MAX: %s", match.group(1), actor.name)
            self._answer(callback_id, "Оплата отмечена ✅", new_text)
        elif result is PayResult.ALREADY_PAID:
            self._answer(callback_id, "Уже отмечено как оплаченное", new_text)
        else:
            self._answer(callback_id, "Платёж не найден или прекращён", new_text)

    # ---------- привязка к пользователю панели ----------

    def _linked(self, user: dict[str, Any]):  # noqa: ANN202
        with self._session_factory() as db:
            link = links.find(db, "max", user.get("user_id"))
            if link is not None:
                db.expunge(link)
            return link

    def _actor(self, user: dict[str, Any], link) -> audit.Actor:  # noqa: ANN001
        if link is None:
            return audit.max_actor(user)
        with self._session_factory() as db:
            return links.actor_for(db, self._settings, link)

    def _process_start(self, chat_id: Any, user: dict[str, Any], payload: Any) -> None:
        """«Начать» по ссылке с кодом (или /start <код> в диалоге) привязывает аккаунт к пользователю панели."""
        if chat_id is None or user.get("is_bot"):
            return
        if not payload:
            self._send(chat_id, links.START_HELP)
            return
        with self._session_factory() as db:
            result = links.redeem(
                db, self._settings, "max", str(payload), str(user.get("user_id")), str(chat_id), audit.max_actor(user).name
            )
        self._send(chat_id, result.message)

    def _process_command(self, recipient: dict[str, Any], user: dict[str, Any], command: str) -> None:
        """Списки платежей видят чат напоминаний и привязанные пользователи в своём диалоге. Чужие чаты молчат."""
        chat_id = recipient.get("chat_id")
        if not self._is_our_chat(recipient):
            if recipient.get("chat_type") != "dialog":
                return
            link = self._linked(user)
            if link is None or link.chat_id != str(chat_id):
                self._send(chat_id, bot_commands.NO_ACCESS if command != "help" else bot_commands.HELP)
                return
        with self._session_factory() as db:
            text = bot_commands.reply(db, command, self._today())
        self._send(chat_id, text, html=True)

    def _send(self, chat_id: Any, text: str, html: bool = False) -> None:
        body: dict[str, Any] = {"text": text}
        if html:
            body["format"] = "html"
        try:
            self._api.call("POST", "/messages", query={"chat_id": chat_id}, body=body)
        except MaxError as error:
            logger.warning("Ответ в личку MAX не ушёл: %s", error)

    # ---------- авторизация ----------

    def _is_our_chat(self, recipient: dict[str, Any]) -> bool:
        try:
            return recipient.get("chat_id") == self._api.chat_id_number()
        except MaxError:
            return False

    def _is_authorized(self, user: dict[str, Any], recipient: dict[str, Any]) -> bool | None:
        """True/False по списку чата, None если проверить не удалось (трактуется как отказ)."""
        user_id = user.get("user_id")
        if not isinstance(user_id, int) or user.get("is_bot"):
            return False

        allowed_ids = self._settings.allowed_max_ids
        if allowed_ids and user_id not in allowed_ids:
            return False

        # Диалог с ботом: кроме бота в нём один человек, и это нажавший
        if recipient.get("chat_type") == "dialog":
            return True

        cached = self._member_cache.get(user_id)
        if cached and cached[0] > time.monotonic():
            return cached[1]

        try:
            result = self._api.call(
                "GET", f"/chats/{self._api.chat_id_number()}/members", query={"user_ids": str(user_id)}
            )
        except MaxError as error:
            logger.error("Проверка участника чата MAX не удалась: %s", error)
            return None

        members = (result or {}).get("members") or []
        is_member = any(member.get("user_id") == user_id for member in members)
        self._member_cache[user_id] = (time.monotonic() + self._cache_ttl, is_member)
        return is_member

    # ---------- действия ----------

    def _answer(self, callback_id: str, notification: str, new_text: str | None = None) -> None:
        body: dict[str, Any] = {"notification": notification}
        if new_text is not None:
            body["message"] = {"text": new_text, "format": "html", "attachments": []}
        try:
            self._api.call("POST", "/answers", query={"callback_id": callback_id}, body=body)
        except MaxError as error:
            logger.warning("Ответ на нажатие в MAX не удался: %s", error)


def build_max_bot(settings: Settings, session_factory: Callable[[], Session]) -> MaxPayButtonBot:
    return MaxPayButtonBot(MaxApi(settings), settings, session_factory)
