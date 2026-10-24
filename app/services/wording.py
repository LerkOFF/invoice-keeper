"""Формулировки напоминаний: один источник для писем, Telegram и MAX, чтобы везде было одинаково.

Сообщения в мессенджерах повторяют письмо: статус цветной точкой сверху, заголовок жирным,
поясняющая фраза, затем платёж, сумма жирным и срок. Разметка HTML (Telegram parse_mode=HTML, MAX format=html).
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from html import escape

DOTS = {"soon": "🟠", "today": "🟠", "overdue": "🔴", "paid": "🟢", "gone": "⚪️"}


def days_phrase(days_left: int) -> str:
    if days_left < 0:
        return f"просрочен на {-days_left} дн."
    return {0: "сегодня", 1: "завтра"}.get(days_left, f"через {days_left} дн.")


def format_money(amount: Decimal, currency: str) -> str:
    """45000.00 RUB -> «45 000.00 RUB»."""
    whole, _, frac = f"{amount:.2f}".partition(".")
    return f"{int(whole):,}".replace(",", " ") + f".{frac} {currency}"


@dataclass(frozen=True)
class Wording:
    status: str  # soon, today, overdue
    chip: str
    title: str
    lead: str


def describe(days_left: int, overdue_notice: bool = False) -> Wording:
    if overdue_notice:
        return Wording(
            "overdue",
            f"Просрочено на {-days_left} дн.",
            "Платёж просрочен",
            "Срок оплаты прошёл, а оплата так и не отмечена. Оплатите и отметьте её в панели.",
        )
    if days_left < 0:
        return Wording(
            "overdue",
            f"Просрочено на {-days_left} дн.",
            "Напоминание об оплате",
            "Срок оплаты уже прошёл. Оплатите как можно скорее и отметьте оплату в панели.",
        )
    if days_left == 0:
        return Wording("today", "Срок сегодня", "Напоминание об оплате", "Сегодня последний день оплаты.")
    if days_left == 1:
        return Wording("soon", "Срок завтра", "Напоминание об оплате", "Завтра последний день оплаты.")
    return Wording("soon", f"Через {days_left} дн.", "Напоминание об оплате", f"До срока оплаты осталось {days_left} дн.")


def _rows(name: str, money: str, due: date, days_left: int | None, html: bool) -> list[str]:
    e = escape if html else (lambda value: value)
    amount = f"<b>{e(money)}</b>" if html else money
    when = f"{due:%d.%m.%Y}" + (f" ({days_phrase(days_left)})" if days_left is not None else "")
    return [f"Платёж: {e(name)}", f"Сумма: {amount}", f"Срок оплаты: {when}"]


def reminder_message(
    name: str,
    money: str,
    due: date,
    days_left: int,
    overdue_notice: bool = False,
    html: bool = True,
    details: str | None = None,
) -> str:
    """Напоминание для мессенджера. html=False даёт ту же структуру обычным текстом (для webhook)."""
    w = describe(days_left, overdue_notice)
    title = f"<b>{escape(w.title)}</b>" if html else w.title
    rows = _rows(name, money, due, days_left, html)
    if details:
        rows.append(f"Реквизиты: {escape(details) if html else details}")
    return "\n".join([f"{DOTS[w.status]} {w.chip}", title, w.lead, "", *rows])


def paid_message(name: str, money: str, due: date, paid_at: date | None, who: str | None) -> str:
    """Во что превращается напоминание после нажатия «Оплачено»: тот же вид, статус зелёный."""
    paid = f"{paid_at:%d.%m.%Y}" if paid_at else "—"
    lines = [f"{DOTS['paid']} Оплачено {paid}", "<b>Оплата отмечена</b>"]
    if who:
        lines.append(f"Отметил(а): {escape(who)}")
    return "\n".join([*lines, "", *_rows(name, money, due, None, True)])


def gone_message(name: str, money: str, due: date) -> str:
    return "\n".join(
        [f"{DOTS['gone']} Платёж прекращён", "<b>Отмечать больше нечего</b>", "Регулярный платёж удалён из панели.", "", *_rows(name, money, due, None, True)]
    )
