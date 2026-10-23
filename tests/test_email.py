import smtplib
from datetime import timedelta
from decimal import Decimal
from email import message_from_bytes, policy

import pytest

from app.core.config import Settings
from app.services import mailer
from app.services.mailer import EmailNotifier, build_email
from app.services.notify import NotifyError, Reminder
from app.services.telegram import build_notifiers
from tests.helpers import TODAY

CONFIG = dict(smtp_host="smtp.example.com", smtp_from="Invoice Keeper <bot@example.com>", smtp_to="a@example.com, b@example.com")


def reminder(**over) -> Reminder:
    base = dict(
        occurrence_id=7, payment_id=3, name="Аренда офиса", amount=Decimal("45000.00"), currency="RUB",
        due_date=TODAY + timedelta(days=2), days_left=2, text="🔔 Напоминание об оплате\n\nПлатёж: Аренда офиса",
    )
    return Reminder(**(base | over))


class FakeSMTP:
    """Запоминает, что сделал клиент SMTP; умеет падать на любом шаге."""

    instances: list["FakeSMTP"] = []
    fail_on: str | None = None

    def __init__(self, host, port, timeout=None, context=None):
        self.host, self.port, self.ssl = host, port, context is not None
        self.calls: list[str] = []
        self.sent = []
        FakeSMTP.instances.append(self)
        self._maybe_fail("connect")

    def _maybe_fail(self, step):
        if FakeSMTP.fail_on == step:
            if step == "login":
                raise smtplib.SMTPAuthenticationError(535, b"bad credentials for app-pass-123")
            raise ConnectionRefusedError("refused")

    def ehlo(self):
        self.calls.append("ehlo")

    def starttls(self, context=None):
        self.calls.append("starttls")

    def login(self, user, password):
        self.calls.append(f"login:{user}")
        self._maybe_fail("login")

    def send_message(self, message):
        self._maybe_fail("send")
        self.sent.append(message)

    def quit(self):
        self.calls.append("quit")


@pytest.fixture(autouse=True)
def fake_smtp(monkeypatch):
    FakeSMTP.instances, FakeSMTP.fail_on = [], None
    monkeypatch.setattr(mailer.smtplib, "SMTP", FakeSMTP)
    monkeypatch.setattr(mailer.smtplib, "SMTP_SSL", FakeSMTP)
    return FakeSMTP


def test_configured_only_with_host_sender_and_recipients():
    assert EmailNotifier(Settings(**CONFIG)).configured
    assert not EmailNotifier(Settings()).configured
    assert not EmailNotifier(Settings(**(CONFIG | {"smtp_to": " , "}))).configured
    assert not EmailNotifier(Settings(**(CONFIG | {"smtp_from": ""}))).configured
    assert Settings(smtp_to="a@x.ru; b@x.ru,c@x.ru").smtp_recipients == ["a@x.ru", "b@x.ru", "c@x.ru"]


def test_ssl_connection_with_login_sends_to_all_recipients():
    EmailNotifier(Settings(**CONFIG, smtp_user="bot", smtp_password="app-pass-123", smtp_port=465)).send(reminder())

    [smtp] = FakeSMTP.instances
    assert (smtp.host, smtp.port, smtp.ssl) == ("smtp.example.com", 465, True)
    assert smtp.calls == ["login:bot", "quit"]
    [message] = smtp.sent
    assert message["To"] == "a@example.com, b@example.com"
    assert message["From"] == "Invoice Keeper <bot@example.com>"


def test_starttls_and_plain_modes():
    EmailNotifier(Settings(**CONFIG, smtp_security="starttls", smtp_port=587)).send(reminder())
    EmailNotifier(Settings(**CONFIG, smtp_security="none", smtp_port=25)).send(reminder())
    tls, plain = FakeSMTP.instances
    assert tls.calls == ["ehlo", "starttls", "ehlo", "quit"] and not tls.ssl
    assert plain.calls == ["quit"]  # без логина, если пользователь не задан


def test_email_content_has_subject_text_html_and_panel_link():
    message = build_email(reminder(), Settings(**CONFIG, public_url="https://keeper.example.com/"))
    assert message["Subject"] == "Напоминание об оплате: Аренда офиса, 45 000.00 RUB до 25.10.2026"
    parsed = message_from_bytes(message.as_bytes(), policy=policy.default)
    text = parsed.get_body(("plain",)).get_content()
    html = parsed.get_body(("html",)).get_content()
    assert "Платёж: Аренда офиса" in text and "Открыть панель: https://keeper.example.com" in text
    assert "через 2 дн." in html and 'href="https://keeper.example.com"' in html


def test_header_injection_and_html_injection_are_neutralised():
    evil = reminder(name="Аренда\r\nBcc: victim@example.com <script>x</script>")
    message = build_email(evil, Settings(**CONFIG))
    assert "\n" not in message["Subject"] and message["Bcc"] is None
    html = message_from_bytes(message.as_bytes(), policy=policy.default).get_body(("html",)).get_content()
    assert "<script>" not in html and "&lt;script&gt;" in html


def test_overdue_wording():
    message = build_email(reminder(days_left=-4), Settings(**CONFIG))
    html = message_from_bytes(message.as_bytes(), policy=policy.default).get_body(("html",)).get_content()
    assert "просрочен на 4 дн." in html


@pytest.mark.parametrize("step", ["connect", "login", "send"])
def test_failures_become_notify_errors_without_password(step):
    FakeSMTP.fail_on = step
    with pytest.raises(NotifyError) as error:
        EmailNotifier(Settings(**CONFIG, smtp_user="bot", smtp_password="app-pass-123")).send(reminder())
    assert "app-pass-123" not in str(error.value)


def test_not_configured_raises():
    with pytest.raises(NotifyError):
        EmailNotifier(Settings()).send(reminder())


def test_email_is_one_of_the_channels():
    names = [n.name for n in build_notifiers(Settings(**CONFIG))]
    assert names == ["telegram", "max", "email", "webhook"]


def test_email_channel_takes_part_in_reminders(db):
    from sqlalchemy import select

    from app.models import ReminderDelivery
    from app.services.reminders import send_due_reminders
    from tests.test_reminders import add_payment

    add_payment(db, TODAY + timedelta(days=1))
    assert send_due_reminders(db, [EmailNotifier(Settings(**CONFIG))], Settings(), TODAY) == 1
    assert send_due_reminders(db, [EmailNotifier(Settings(**CONFIG))], Settings(), TODAY) == 0
    assert len(FakeSMTP.instances) == 1
    assert [d.channel for d in db.scalars(select(ReminderDelivery))] == ["email"]


# ---------- оформление в стиле сайта ----------


def _html(message):
    return message_from_bytes(message.as_bytes(), policy=policy.default).get_body(("html",)).get_content()


def test_logo_is_embedded_not_loaded_from_the_internet():
    message = build_email(reminder(), Settings(**CONFIG))
    html = _html(message)
    assert 'src="cid:invoice-keeper-logo"' in html and "http" not in html.split("cid:")[0][-40:]
    parsed = message_from_bytes(message.as_bytes(), policy=policy.default)
    images = [p for p in parsed.walk() if p.get_content_type() == "image/png"]
    assert len(images) == 1 and images[0]["Content-ID"] == "<invoice-keeper-logo>"


@pytest.mark.parametrize(
    ("over", "chip", "title", "color"),
    [
        ({"days_left": 2}, "Через 2 дн.", "Напоминание об оплате", "#ff7a00"),
        ({"days_left": 1}, "Срок завтра", "Напоминание об оплате", "#ff7a00"),
        ({"days_left": 0}, "Срок сегодня", "Напоминание об оплате", "#ff7a00"),
        ({"days_left": -5}, "Просрочено на 5 дн.", "Напоминание об оплате", "#ff4757"),
        ({"days_left": -3, "overdue_notice": True}, "Просрочено на 3 дн.", "Платёж просрочен", "#ff4757"),
    ],
)
def test_every_kind_of_email_has_its_status_and_title(over, chip, title, color):
    html = _html(build_email(reminder(**over), Settings(**CONFIG, public_url="https://keeper.example.com")))
    assert chip in html and f">{title}<" in html and color in html
    assert "45 000.00 RUB" in html and "Открыть панель" in html


def test_overdue_notice_subject_and_text():
    message = build_email(reminder(days_left=-3, overdue_notice=True), Settings(**CONFIG))
    assert message["Subject"].startswith("Платёж просрочен: Аренда офиса, 45 000.00 RUB, срок был")
    text = message_from_bytes(message.as_bytes(), policy=policy.default).get_body(("plain",)).get_content()
    assert "Платёж просрочен" in text and "просрочен на 3 дн." in text


def test_no_panel_button_without_public_url():
    html = _html(build_email(reminder(), Settings(**CONFIG)))
    assert "Открыть панель" not in html


def test_preheader_and_dark_mode_support():
    html = _html(build_email(reminder(), Settings(**CONFIG)))
    assert "До срока оплаты осталось 2 дн." in html  # скрытый анонс для списка писем
    assert 'name="color-scheme" content="light dark"' in html and "prefers-color-scheme: dark" in html


def test_message_id_uses_sender_domain_and_marks_auto_generated():
    message = build_email(reminder(), Settings(**CONFIG))
    assert message["Message-ID"].endswith("@example.com>")
    assert message["Auto-Submitted"] == "auto-generated"
