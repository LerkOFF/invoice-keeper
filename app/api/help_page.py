import re

from fastapi import APIRouter

from app.api.deps import CurrentPrincipal, SettingsDep
from app.core.config import Settings
from app.schemas.help import ContactOut, HelpContactsOut, HelpOut
from app.services import links
from app.services.notify import NotifyError
from app.services.telegram import build_notifiers

router = APIRouter(prefix="/help", tags=["help"])

_TELEGRAM_NAME = re.compile(r"(?:https?://t\.me/|@)?([A-Za-z][A-Za-z0-9_]{3,31})/?")
_EMAIL = re.compile(r"[^@\s<>\"]+@[^@\s<>\"]+\.[^@\s<>\"]+")
_BOT_LINKS = {"telegram": "https://t.me/{}", "max": "https://max.ru/{}"}


def _telegram(value: str) -> ContactOut | None:
    match = _TELEGRAM_NAME.fullmatch(value.strip())
    return ContactOut(label=f"@{match[1]}", url=f"https://t.me/{match[1]}") if match else None


def _email(value: str) -> ContactOut | None:
    value = value.strip()
    return ContactOut(label=value, url=f"mailto:{value}") if _EMAIL.fullmatch(value) else None


def _url(value: str) -> ContactOut | None:
    value = value.strip()
    if not value.lower().startswith(("https://", "http://")) or any(c in value for c in " <>\""):
        return None
    return ContactOut(label=re.sub(r"^https?://(www\.)?", "", value).rstrip("/"), url=value)


def contacts_of(settings: Settings) -> HelpContactsOut:
    """Контакты из .env. Значение, похожее на мусор, просто не показывается."""
    return HelpContactsOut(
        telegram=_telegram(settings.support_telegram) if settings.support_telegram else None,
        email=_email(settings.support_email) if settings.support_email else None,
        url=_url(settings.support_url) if settings.support_url else None,
    )


def _bots(settings: Settings) -> dict[str, ContactOut]:
    result = {}
    for messenger in links.MESSENGERS:
        if not links.bot_available(settings, messenger):
            continue
        try:
            name = links.bot_username(settings, messenger)
        except NotifyError:
            continue  # мессенджер недоступен: страница помощи всё равно открывается
        result[messenger] = ContactOut(label=f"@{name}" if messenger == "telegram" else name, url=_BOT_LINKS[messenger].format(name))
    return result


@router.get(
    "",
    response_model=HelpOut,
    summary="Сведения для страницы «Помощь»",
    description="Контакты поддержки из .env, боты и каналы напоминаний, настройки сроков. Доступно всем вошедшим.",
)
def help_info(_principal: CurrentPrincipal, settings: SettingsDep) -> HelpOut:
    return HelpOut(
        contacts=contacts_of(settings),
        bots=_bots(settings),
        channels=[n.name for n in build_notifiers(settings) if n.configured],
        reminder_days=settings.reminder_days,
        overdue_reminders=settings.overdue_reminders,
        timezone=settings.app_timezone,
    )
