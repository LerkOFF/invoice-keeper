import hashlib
import logging
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models import MessengerLink, MessengerLinkCode, Role, User
from app.services import audit
from app.services.auth import Principal
from app.services.notify import NotifyError, Reminder

logger = logging.getLogger("invoice_keeper")

MESSENGERS = ("telegram", "max")
MESSENGER_TITLES = {"telegram": "Telegram", "max": "MAX"}
CODE_TTL = timedelta(minutes=10)
START_HELP = (
    "Здравствуйте! Это бот Invoice Keeper. Чтобы получать напоминания об оплате лично, "
    "откройте панель → «Мессенджеры» → «Привязать» и перейдите по ссылке оттуда."
)

# Ошибки, после которых повторять отправку в личку бессмысленно: человек заблокировал бота или удалил чат
_PERMANENT_MARKERS = ("blocked", "chat not found", "user is deactivated", "403", "forbidden", "not.found", "chat.denied")


@dataclass(frozen=True)
class Owner:
    """Чей аккаунт: обычный пользователь (user_id) или администратор из .env (is_admin)."""

    user_id: int | None
    is_admin: bool

    @staticmethod
    def of(principal: Principal) -> "Owner":
        return Owner(None, True) if principal.is_admin else Owner(principal.id, False)

    def where(self, model):  # noqa: ANN001
        return model.is_admin.is_(True) if self.is_admin else model.user_id == self.user_id


def _hash(code: str) -> str:
    return hashlib.sha256(code.encode()).hexdigest()


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def owner_login(db: Session, settings: Settings, link: MessengerLink) -> tuple[str, Role]:
    if link.is_admin:
        return settings.admin_login, Role.ADMIN
    user = db.get(User, link.user_id)
    return (user.login if user else f"id {link.user_id}"), Role.USER


def links_of(db: Session, owner: Owner) -> dict[str, MessengerLink]:
    return {link.messenger: link for link in db.scalars(select(MessengerLink).where(owner.where(MessengerLink)))}


def create_code(db: Session, owner: Owner, messenger: str) -> tuple[str, datetime]:
    """Новый одноразовый код. Прежние неиспользованные коды владельца для этого мессенджера сгорают."""
    db.execute(delete(MessengerLinkCode).where(owner.where(MessengerLinkCode), MessengerLinkCode.messenger == messenger))
    db.execute(delete(MessengerLinkCode).where(MessengerLinkCode.expires_at < datetime.now(UTC)))
    code = secrets.token_urlsafe(18)  # [A-Za-z0-9_-], подходит для параметра start в Telegram и MAX
    expires_at = datetime.now(UTC) + CODE_TTL
    db.add(
        MessengerLinkCode(
            code_hash=_hash(code), messenger=messenger, user_id=owner.user_id, is_admin=owner.is_admin, expires_at=expires_at
        )
    )
    db.commit()
    return code, expires_at


@dataclass(frozen=True)
class Redeemed:
    ok: bool
    message: str
    login: str | None = None


def redeem(
    db: Session,
    settings: Settings,
    messenger: str,
    code: str,
    external_user_id: str,
    chat_id: str,
    display_name: str,
) -> Redeemed:
    """Привязка по коду из ссылки. Код одноразовый; аккаунт мессенджера переезжает к новому владельцу,
    прежний аккаунт владельца в этом мессенджере отвязывается."""
    row = db.scalar(select(MessengerLinkCode).where(MessengerLinkCode.code_hash == _hash(code.strip())))
    if row is None or row.messenger != messenger:
        return Redeemed(False, "Код не подошёл. Получите новую ссылку в панели: «Мессенджеры» → «Привязать».")
    db.delete(row)
    if _aware(row.expires_at) <= datetime.now(UTC):
        db.commit()
        return Redeemed(False, "Ссылка устарела. Получите новую в панели: «Мессенджеры» → «Привязать».")
    if not row.is_admin and (row.user_id is None or db.get(User, row.user_id) is None):
        db.commit()
        return Redeemed(False, "Пользователь, для которого создана ссылка, больше не существует.")

    owner = Owner(row.user_id, row.is_admin)
    db.execute(delete(MessengerLink).where(MessengerLink.messenger == messenger, MessengerLink.external_user_id == external_user_id))
    db.execute(delete(MessengerLink).where(MessengerLink.messenger == messenger, owner.where(MessengerLink)))
    link = MessengerLink(
        messenger=messenger,
        user_id=owner.user_id,
        is_admin=owner.is_admin,
        external_user_id=external_user_id,
        chat_id=chat_id,
        display_name=display_name[:100],
    )
    db.add(link)
    db.flush()
    login, role = owner_login(db, settings, link)
    audit.record(
        db,
        "messenger.link",
        audit.Actor(role.value, login),
        "messenger",
        link.id,
        {"messenger": messenger, "account": display_name, "source": messenger},
    )
    db.commit()
    return Redeemed(True, f"Готово: {MESSENGER_TITLES[messenger]} привязан к пользователю {login}. Сюда будут приходить напоминания об оплате.", login)


def unlink(db: Session, settings: Settings, owner: Owner, messenger: str, actor: audit.Actor) -> bool:
    link = links_of(db, owner).get(messenger)
    if link is None:
        return False
    audit.record(db, "messenger.unlink", actor, "messenger", link.id, {"messenger": messenger, "account": link.display_name})
    db.delete(link)
    db.commit()
    return True


def find(db: Session, messenger: str, external_user_id: Any) -> MessengerLink | None:
    if external_user_id is None:
        return None
    return db.scalar(
        select(MessengerLink).where(MessengerLink.messenger == messenger, MessengerLink.external_user_id == str(external_user_id))
    )


def actor_for(db: Session, settings: Settings, link: MessengerLink) -> audit.Actor:
    login, role = owner_login(db, settings, link)
    return audit.Actor(role.value, login)


# ---------- личные напоминания ----------


def is_permanent(error: Exception) -> bool:
    text = str(error).lower()
    return any(marker in text for marker in _PERMANENT_MARKERS)


class PersonalNotifier:
    """Напоминание в личный чат привязанного пользователя. Имя канала своё у каждого получателя,
    поэтому доставка и защита от дублей считаются отдельно для каждого человека."""

    def __init__(self, link: MessengerLink, settings: Settings, api: Any = None) -> None:
        owner = "admin" if link.is_admin else f"u{link.user_id}"
        self.name = f"{link.messenger}:{owner}"
        self._link = link
        self._settings = settings
        self._api = api

    @property
    def configured(self) -> bool:
        s = self._settings
        token = s.telegram_bot_token if self._link.messenger == "telegram" else s.max_bot_token
        return bool(token.strip())

    def _client(self) -> Any:
        if self._api is not None:
            return self._api
        if self._link.messenger == "telegram":
            from app.services.telegram import TelegramApi

            return TelegramApi(self._settings)
        from app.services.max_api import MaxApi

        return MaxApi(self._settings)

    def send(self, reminder: Reminder) -> None:
        api = self._client()
        if self._link.messenger == "telegram":
            from app.services.telegram import pay_keyboard

            payload: dict[str, Any] = {"chat_id": self._link.chat_id, "text": reminder.html or reminder.text, "disable_web_page_preview": True}
            if reminder.html:
                payload["parse_mode"] = "HTML"
            paid_button = reminder.occurrence_id if self._settings.telegram_buttons_enabled else None
            if markup := pay_keyboard(paid_button, reminder.pay_url):
                payload["reply_markup"] = markup
            api.call("sendMessage", payload)
        else:
            from app.services.max_api import pay_keyboard as max_keyboard

            body: dict[str, Any] = {"text": reminder.html or reminder.text}
            if reminder.html:
                body["format"] = "html"
            paid_button = reminder.occurrence_id if self._settings.max_buttons_enabled else None
            if keyboard := max_keyboard(paid_button, reminder.pay_url):
                body["attachments"] = [keyboard]
            api.call("POST", "/messages", query={"chat_id": int(self._link.chat_id), "disable_link_preview": "true"}, body=body)


def personal_notifiers(db: Session, settings: Settings) -> list[PersonalNotifier]:
    return [PersonalNotifier(link, settings) for link in db.scalars(select(MessengerLink).order_by(MessengerLink.id))]


def permanent_failure(error: NotifyError) -> bool:
    return is_permanent(error)


# ---------- ссылка на бота ----------

_bot_usernames: dict[str, str] = {}


def bot_available(settings: Settings, messenger: str) -> bool:
    token = settings.telegram_bot_token if messenger == "telegram" else settings.max_bot_token
    return bool(token.strip())


def bot_username(settings: Settings, messenger: str, api: Any = None) -> str:
    """Имя бота для ссылки t.me/<имя> или max.ru/<имя>. Узнаётся у API один раз за жизнь процесса."""
    if messenger in _bot_usernames:
        return _bot_usernames[messenger]
    if messenger == "telegram":
        from app.services.telegram import TelegramApi

        username = ((api or TelegramApi(settings)).call("getMe") or {}).get("username")
    else:
        from app.services.max_api import MaxApi

        username = ((api or MaxApi(settings)).call("GET", "/me") or {}).get("username")
    if not username:
        raise NotifyError("бот не сообщил своё имя")
    _bot_usernames[messenger] = username
    return username


def start_url(messenger: str, username: str, code: str) -> str:
    if messenger == "telegram":
        return f"https://t.me/{username}?start={code}"
    return f"https://max.ru/{username}?start={code}"
