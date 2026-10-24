import json
from datetime import date

import httpx
import pytest
from sqlalchemy import create_engine, inspect, text

from app.core.config import Settings
from app.core.db import migrate
from app.services import max_api, telegram
from app.services.mailer import build_email
from tests.helpers import B
from tests.test_email import reminder

URL = "https://my.aeza.ru/billing"


def create(admin, **extra):
    body = {"name": "Сервер Aeza", "amount": "20", "currency": "USD", "first_due_date": "2026-10-25", **extra}
    response = admin.post(f"{B}/recurring-payments", json=body)
    assert response.status_code == 201, response.text
    return response.json()


def test_link_and_details_are_saved_and_shown_in_periods(admin, user):
    payment = create(admin, pay_url=URL, pay_details="Договор 42")
    assert payment["pay_url"] == URL and payment["pay_details"] == "Договор 42"
    period = user.get(f"{B}/payment-occurrences").json()[0]
    assert period["pay_url"] == URL and period["pay_details"] == "Договор 42"


@pytest.mark.parametrize("bad", ["javascript:alert(1)", "ftp://files.example.com", "https://a b", 'https://x"y'])
def test_unsafe_links_are_rejected(admin, bad):
    body = {"name": "x", "amount": "1", "currency": "RUB", "first_due_date": "2026-10-25", "pay_url": bad}
    assert admin.post(f"{B}/recurring-payments", json=body).status_code == 422


def test_link_is_edited_cleared_and_logged(admin):
    payment = create(admin, pay_url=URL)
    url = f"{B}/recurring-payments/{payment['id']}"
    edited = admin.patch(url, json={"pay_url": "https://pay.example.com", "pay_details": "ИНН 7700000000"}).json()
    assert edited["pay_url"] == "https://pay.example.com" and edited["pay_details"] == "ИНН 7700000000"
    cleared = admin.patch(url, json={"pay_url": None, "pay_details": ""}).json()
    assert cleared["pay_url"] is None and cleared["pay_details"] is None
    entry = admin.get(f"{B}/audit-log", params={"action": "payment.update"}).json()[0]
    assert entry["details"]["pay_url_before"] == "https://pay.example.com"


def test_reminder_text_has_details_and_keyboard_has_pay_link():
    from app.services import wording

    message = wording.reminder_message("Аренда", "100.00 RUB", date(2026, 10, 25), 2, details="Счёт <42>")
    assert message.endswith("Реквизиты: Счёт &lt;42&gt;")
    assert telegram.pay_keyboard(7, URL) == {
        "inline_keyboard": [
            [{"text": "✅ Оплачено", "callback_data": "paid:7"}],
            [{"text": "💳 Оплатить", "url": URL}],
        ]
    }
    assert telegram.pay_keyboard(None, URL) == {"inline_keyboard": [[{"text": "💳 Оплатить", "url": URL}]]}
    assert telegram.pay_keyboard(None) is None
    buttons = max_api.pay_keyboard(7, URL)["payload"]["buttons"]
    assert buttons[1] == [{"type": "link", "text": "💳 Оплатить", "url": URL}]


def test_telegram_sends_pay_link_even_when_paid_button_is_off():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"ok": True, "result": {}})

    notifier = telegram.TelegramNotifier(
        Settings(telegram_bot_token="t", telegram_chat_id="-1", telegram_buttons_enabled=False),
        transport=httpx.MockTransport(handler),
    )
    notifier.send(reminder(pay_url=URL))
    assert seen["body"]["reply_markup"] == {"inline_keyboard": [[{"text": "💳 Оплатить", "url": URL}]]}


def test_email_has_pay_button_and_details():
    settings = Settings(smtp_from="bot@example.com", smtp_to="team@example.com", public_url="https://invoice-keeper.ru")
    message = build_email(reminder(pay_url=URL, pay_details="Договор 42"), settings)
    text_part = message.get_body(preferencelist=("plain",)).get_content()
    html_part = message.get_body(preferencelist=("html",)).get_content()
    assert f"Оплатить: {URL}" in text_part and "Реквизиты: Договор 42" in text_part
    assert f'href="{URL}"' in html_part and ">Оплатить</a>" in html_part and "Договор 42" in html_part


def test_migration_adds_link_columns(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path}/old.db")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE recurring_payments (id INTEGER PRIMARY KEY, amount_minor INTEGER)"))
        conn.execute(text("CREATE TABLE payment_occurrences (id INTEGER PRIMARY KEY, recurring_id INTEGER)"))
    migrate(engine)
    migrate(engine)
    assert {"pay_url", "pay_details"} <= {c["name"] for c in inspect(engine).get_columns("recurring_payments")}
