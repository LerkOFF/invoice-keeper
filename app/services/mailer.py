import logging
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from html import escape

from app.core.config import Settings
from app.services.notify import NotifyError, Reminder

logger = logging.getLogger("invoice_keeper")


def _one_line(value: str) -> str:
    """В заголовок письма нельзя пускать переводы строк из названия платежа."""
    return " ".join(value.split())


def _days_phrase(days_left: int) -> str:
    if days_left < 0:
        return f"просрочен на {-days_left} дн."
    return {0: "сегодня", 1: "завтра"}.get(days_left, f"через {days_left} дн.")


def build_email(reminder: Reminder, settings: Settings) -> EmailMessage:
    from app.services.reminders import format_money  # здесь, чтобы не было цикла импорта

    money = format_money(reminder.amount, reminder.currency)
    due = f"{reminder.due_date:%d.%m.%Y}"
    panel_url = settings.public_url.rstrip("/")

    message = EmailMessage()
    title = "Платёж просрочен" if reminder.overdue_notice else "Напоминание об оплате"
    subject = f"{reminder.name}, {money}, срок был {due}" if reminder.overdue_notice else f"{reminder.name}, {money} до {due}"
    message["Subject"] = _one_line(f"{title}: {subject}")
    message["From"] = settings.smtp_from
    message["To"] = ", ".join(settings.smtp_recipients)
    message["Date"] = formatdate(localtime=False)
    message["Message-ID"] = make_msgid(domain="invoice-keeper")
    message.set_content(reminder.text + (f"\n\nОткрыть панель: {panel_url}" if panel_url else ""))
    panel = f'<p><a href="{escape(panel_url, quote=True)}">Открыть панель</a></p>' if panel_url else ""
    message.add_alternative(
        '<html><body style="font-family:sans-serif">'
        f"<h2>{title}</h2>"
        f"<p><b>Платёж:</b> {escape(reminder.name)}<br><b>Сумма:</b> {escape(money)}<br>"
        f"<b>Срок оплаты:</b> {due} ({_days_phrase(reminder.days_left)})</p>{panel}</body></html>",
        subtype="html",
    )
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
