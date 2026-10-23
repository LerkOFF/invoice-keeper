import logging
import smtplib
import ssl
from email.message import EmailMessage
from dataclasses import dataclass
from email.utils import formatdate, make_msgid
from html import escape
from pathlib import Path

from app.core.config import Settings
from app.services import wording
from app.services.notify import NotifyError, Reminder

logger = logging.getLogger("invoice_keeper")


def _one_line(value: str) -> str:
    """В заголовок письма нельзя пускать переводы строк из названия платежа."""
    return " ".join(value.split())


def _days_phrase(days_left: int) -> str:
    if days_left < 0:
        return f"просрочен на {-days_left} дн."
    return {0: "сегодня", 1: "завтра"}.get(days_left, f"через {days_left} дн.")


LOGO = Path(__file__).resolve().parent.parent / "web" / "static" / "brand" / "icon-192.png"
LOGO_CID = "invoice-keeper-logo"

# Цвета и шрифт из оформления панели (палитра aeza, светлая тема): письма выглядят как сайт
FONT = "Inter, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif"
INK = "#000000"
TEXT = "#585858"
MUTED = "#919191"
PAGE = "#f4f4f4"
CARD = "#ffffff"
LINE = "#ececec"
STATUS = {
    "soon": ("#ff7a00", "#d46600", "#fff3e8"),
    "today": ("#ff7a00", "#d46600", "#fff3e8"),
    "overdue": ("#ff4757", "#e0283a", "#ffecee"),
}


@dataclass(frozen=True)
class EmailContent:
    subject: str
    preheader: str
    status: str  # soon, today, overdue
    chip: str
    title: str
    lead: str


def describe(reminder: Reminder, money: str, due: str) -> EmailContent:
    """Тема и анонс письма; статус, заголовок и фраза общие с мессенджерами (services/wording.py)."""
    w = wording.describe(reminder.days_left, reminder.overdue_notice)
    if reminder.overdue_notice:
        subject = f"Платёж просрочен: {reminder.name}, {money}, срок был {due}"
        preheader = f"Срок прошёл {-reminder.days_left} дн. назад, а оплата так и не отмечена."
    else:
        subject = f"Напоминание об оплате: {reminder.name}, {money} до {due}"
        preheader = f"Срок уже прошёл: {due}." if reminder.days_left < 0 else f"{w.lead} {reminder.name}, {money}."
    return EmailContent(subject, preheader, w.status, w.chip, w.title, w.lead)


def render_text(reminder: Reminder, content: EmailContent, money: str, due: str, panel_url: str) -> str:
    lines = [
        content.title,
        content.chip,
        "",
        content.lead,
        "",
        f"Платёж: {reminder.name}",
        f"Сумма: {money}",
        f"Срок оплаты: {due} ({_days_phrase(reminder.days_left)})",
    ]
    if panel_url:
        lines += ["", f"Открыть панель: {panel_url}"]
    lines += ["", "—", "Invoice Keeper · напоминания о регулярных платежах", "Письмо отправлено автоматически, отвечать на него не нужно."]
    return "\n".join(lines)


def render_html(reminder: Reminder, content: EmailContent, money: str, due: str, panel_url: str, with_logo: bool) -> str:
    dot, ink, tint = STATUS[content.status]
    e = escape
    row = (
        '<tr><td class="ik-line" style="padding:12px 0;border-top:1px solid {line};font:14px/20px {font};color:{muted};width:40%">{label}</td>'
        '<td class="ik-line ik-ink" style="padding:12px 0;border-top:1px solid {line};font:600 15px/20px {font};color:{ink};text-align:right">{value}</td></tr>'
    )
    rows = "".join(
        row.format(line=LINE, font=FONT, muted=MUTED, ink=INK, label=label, value=value)
        for label, value in (
            ("Срок оплаты", due),
            ("Просрочка" if reminder.days_left < 0 else "До срока", e(_days_phrase(reminder.days_left))),
        )
    )
    logo = (
        f'<img src="cid:{LOGO_CID}" width="36" height="36" alt="" style="display:block;border:0;border-radius:10px">'
        if with_logo
        else ""
    )
    button = (
        f'<tr><td style="padding:28px 0 4px"><a class="ik-btn" href="{e(panel_url, quote=True)}" '
        f'style="display:inline-block;background:{INK};color:#ffffff;text-decoration:none;font:600 15px/20px {FONT};'
        f'padding:14px 26px;border-radius:12px">Открыть панель</a></td></tr>'
        f'<tr><td style="padding:12px 0 0;font:13px/19px {FONT};color:{MUTED}">Отметить оплату можно в панели '
        f"или кнопкой «Оплачено» в сообщении бота.</td></tr>"
        if panel_url
        else ""
    )
    host = e(panel_url.split("://", 1)[-1]) if panel_url else ""
    return f"""<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light dark">
<meta name="supported-color-schemes" content="light dark">
<title>{e(content.title)}</title>
<style>
  @media (prefers-color-scheme: dark) {{
    body, .ik-page {{ background:#000000 !important; }}
    .ik-line {{ border-color:#2c2c2c !important; }}
    .ik-card {{ background:#131313 !important; border-color:#2c2c2c !important; }}
    .ik-ink {{ color:#ffffff !important; }}
    .ik-text {{ color:#bbbbbb !important; }}
    .ik-btn {{ background:#ffffff !important; color:#000000 !important; }}
  }}
  @media (max-width: 600px) {{ .ik-card {{ padding:24px 20px !important; }} .ik-amount {{ font-size:30px !important; }} }}
</style>
</head>
<body style="margin:0;padding:0;background:{PAGE}">
<div style="display:none;max-height:0;overflow:hidden;opacity:0;color:transparent">{e(content.preheader)}</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" class="ik-page" style="background:{PAGE}">
<tr><td align="center" style="padding:32px 12px">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:560px">
    <tr><td style="padding:0 4px 18px">
      <table role="presentation" cellpadding="0" cellspacing="0"><tr>
        <td style="padding-right:10px;vertical-align:middle">{logo}</td>
        <td class="ik-ink" style="vertical-align:middle;font:700 17px/22px {FONT};color:{INK}">Invoice Keeper</td>
      </tr></table>
    </td></tr>
    <tr><td class="ik-card" style="background:{CARD};border:1px solid #e1e1e1;border-radius:20px;padding:32px 32px 28px">
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
        <tr><td><span style="display:inline-block;background:{tint};color:{ink};font:700 13px/18px {FONT};padding:5px 12px 5px 10px;border-radius:999px">
          <span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:{dot};margin-right:7px;vertical-align:1px"></span>{e(content.chip)}</span></td></tr>
        <tr><td class="ik-ink" style="padding:18px 0 6px;font:800 28px/34px {FONT};color:{INK};letter-spacing:-0.02em">{e(content.title)}</td></tr>
        <tr><td class="ik-text" style="padding:0 0 22px;font:15px/22px {FONT};color:{TEXT}">{e(content.lead)}</td></tr>
        <tr><td class="ik-ink ik-amount" style="padding:0 0 4px;font:800 36px/42px {FONT};color:{INK};letter-spacing:-0.02em">{e(money)}</td></tr>
        <tr><td class="ik-text" style="padding:0 0 18px;font:15px/22px {FONT};color:{TEXT}">{e(reminder.name)}</td></tr>
        <tr><td><table role="presentation" width="100%" cellpadding="0" cellspacing="0">{rows}</table></td></tr>
        {button}
      </table>
    </td></tr>
    <tr><td style="padding:20px 8px 0;font:12px/18px {FONT};color:{MUTED};text-align:center">
      Invoice Keeper · напоминания о регулярных платежах{(" · " + host) if host else ""}<br>
      Письмо отправлено автоматически, отвечать на него не нужно.
    </td></tr>
  </table>
</td></tr>
</table>
</body>
</html>"""


def build_email(reminder: Reminder, settings: Settings) -> EmailMessage:
    from app.services.reminders import format_money  # здесь, чтобы не было цикла импорта

    money = format_money(reminder.amount, reminder.currency)
    due = f"{reminder.due_date:%d.%m.%Y}"
    panel_url = settings.public_url.rstrip("/")
    content = describe(reminder, money, due)
    with_logo = LOGO.is_file()

    message = EmailMessage()
    message["Subject"] = _one_line(content.subject)
    message["From"] = settings.smtp_from
    message["To"] = ", ".join(settings.smtp_recipients)
    message["Date"] = formatdate(localtime=False)
    message["Message-ID"] = make_msgid(domain="invoice-keeper")
    message.set_content(render_text(reminder, content, money, due, panel_url))
    message.add_alternative(render_html(reminder, content, money, due, panel_url, with_logo), subtype="html")
    if with_logo:
        # логотип внутри письма: внешние картинки почтовики часто блокируют
        html_part = message.get_payload()[1]
        html_part.add_related(LOGO.read_bytes(), maintype="image", subtype="png", cid=f"<{LOGO_CID}>", filename="logo.png")
    return message


class EmailNotifier:
    """Напоминания по почте через SMTP. Включается, когда заданы SMTP_HOST, SMTP_FROM и SMTP_TO."""

    name = "email"

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    @property
    def configured(self) -> bool:
        s = self._settings
        return bool(s.smtp_host.strip() and s.smtp_from.strip() and s.smtp_recipients)

    def _connect(self) -> smtplib.SMTP:
        s = self._settings
        context = ssl.create_default_context()
        if s.smtp_security == "ssl":
            smtp: smtplib.SMTP = smtplib.SMTP_SSL(s.smtp_host, s.smtp_port, timeout=15, context=context)
        else:
            smtp = smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=15)
            if s.smtp_security == "starttls":
                smtp.ehlo()
                smtp.starttls(context=context)
                smtp.ehlo()
        if s.smtp_user:
            smtp.login(s.smtp_user, s.smtp_password)
        return smtp

    def send(self, reminder: Reminder) -> None:
        if not self.configured:
            raise NotifyError("Почта не настроена: нужны SMTP_HOST, SMTP_FROM и SMTP_TO")
        try:
            message = build_email(reminder, self._settings)
            smtp = self._connect()
            try:
                smtp.send_message(message)
            finally:
                try:
                    smtp.quit()
                except (smtplib.SMTPException, OSError):
                    pass
        except (smtplib.SMTPException, OSError, ValueError) as error:
            password = self._settings.smtp_password
            detail = str(error).replace(password, "***") if password else str(error)
            raise NotifyError(f"почта не отправлена ({type(error).__name__}: {detail[:150]})") from None
