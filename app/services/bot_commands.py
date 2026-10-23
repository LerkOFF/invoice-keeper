from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models import OccurrenceStatus, PaymentOccurrence
from app.services.occurrences import OccurrenceFilter, list_occurrences

# Сколько дней вперёд показывает /todo
TODO_DAYS = 7
# Сколько строк в ответе: сообщение Telegram ограничено 4096 символами
MAX_LINES = 30

# Команда и её синонимы. В группах Telegram команда приходит как /todo@имя_бота
ALIASES = {
    "todo": "todo",
    "pay": "todo",
    "next": "todo",
    "overdue": "overdue",
    "late": "overdue",
    "help": "help",
}

# Для меню команд Telegram (setMyCommands)
MENU = [
    {"command": "todo", "description": f"Что оплатить в ближайшие {TODO_DAYS} дней и что просрочено"},
    {"command": "overdue", "description": "Просроченные платежи"},
    {"command": "help", "description": "Что умеет бот"},
]

HELP = (
    "Я напоминаю об оплате за 3 дня до срока, а кнопка «✅ Оплачено» под напоминанием отмечает оплату.\n\n"
    f"/todo — что оплатить в ближайшие {TODO_DAYS} дней и что уже просрочено\n"
    "/overdue — только просроченные платежи\n"
    "/help — эта справка"
)

NO_ACCESS = (
    "Списки платежей доступны в чате напоминаний или после привязки аккаунта "
    "в панели Invoice Keeper (раздел «Мессенджеры»)."
)


def parse(text: str) -> str | None:
    """Имя команды из текста сообщения или None, если это не наша команда."""
    text = (text or "").strip()
    if not text.startswith("/"):
        return None
    word = text[1:].split(maxsplit=1)[0] if len(text) > 1 else ""
    return ALIASES.get(word.split("@", 1)[0].lower())


def _money(amount_minor: int, currency: str) -> str:
    from app.services.reminders import format_money  # здесь, чтобы не было цикла импорта

    return format_money(Decimal(amount_minor).scaleb(-2), currency)


def _when(occurrence: PaymentOccurrence, today: date) -> str:
    days = (occurrence.due_date - today).days
    if days < 0:
        return f"просрочен на {-days} дн."
    return {0: "сегодня", 1: "завтра"}.get(days, f"через {days} дн.")


def _listing(title: str, items: list[PaymentOccurrence], today: date) -> str:
    lines = []
    totals: dict[str, int] = defaultdict(int)
    for occurrence in items:
        payment = occurrence.recurring_payment
        totals[payment.currency] += occurrence.due_amount_minor
        mark = "🔴" if occurrence.due_date < today else "•"
        lines.append(
            f"{mark} {occurrence.due_date:%d.%m} {payment.name} — "
            f"{_money(occurrence.due_amount_minor, payment.currency)} ({_when(occurrence, today)})"
        )
    if len(lines) > MAX_LINES:
        lines = lines[:MAX_LINES] + [f"…и ещё {len(lines) - MAX_LINES}, полный список в панели"]
    total = ", ".join(_money(minor, currency) for currency, minor in totals.items())
    return f"{title}\n\n" + "\n".join(lines) + f"\n\nИтого: {total}"


def reply(db: Session, command: str, today: date) -> str:
    """Текст ответа на команду. Только чтение: команды ничего не меняют и в журнал не пишут."""
    if command == "help":
        return HELP
    if command == "overdue":
        flt = OccurrenceFilter(status=OccurrenceStatus.UNPAID, overdue=True)
        items = list_occurrences(db, flt, today, limit=1000, offset=0)
        return _listing("🔴 Просроченные платежи", items, today) if items else "Просроченных платежей нет ✅"

    flt = OccurrenceFilter(status=OccurrenceStatus.UNPAID, due_to=today + timedelta(days=TODO_DAYS))
    items = list_occurrences(db, flt, today, limit=1000, offset=0)
    if not items:
        return f"На ближайшие {TODO_DAYS} дней оплат нет, просрочек нет ✅"
    return _listing(f"📋 Что оплатить до {today + timedelta(days=TODO_DAYS):%d.%m.%Y}", items, today)
