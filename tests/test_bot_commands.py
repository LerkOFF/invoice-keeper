from datetime import timedelta
from decimal import Decimal

import pytest

from app.core.db import SessionLocal
from app.models import MessengerLink, RecurringPayment, User
from app.services import bot_commands
from app.services.periods import ensure_occurrences
from tests import test_max_bot as max_tests
from tests import test_telegram_bot as tg_tests
from tests.helpers import TODAY


def add_payment(name, due, amount="100", currency="RUB"):
    with SessionLocal() as db:
        payment = RecurringPayment(name=name, currency=currency, first_due_date=due)
        payment.amount = Decimal(amount)
        db.add(payment)
        db.flush()
        ensure_occurrences(db, payment, TODAY)
        db.commit()


def link(messenger, external_id, chat_id):
    with SessionLocal() as db:
        user = db.query(User).first()
        db.add(
            MessengerLink(
                messenger=messenger, user_id=user.id, external_user_id=str(external_id), chat_id=str(chat_id), display_name="ivan"
            )
        )
        db.commit()


@pytest.mark.parametrize(
    "text, command",
    [
        ("/todo", "todo"),
        ("/todo@aeza_invoice_keeper_bot", "todo"),
        ("/PAY", "todo"),
        ("/overdue", "overdue"),
        ("/help please", "help"),
        ("/start abc", None),
        ("todo", None),
        ("/", None),
        ("", None),
    ],
)
def test_parse(text, command):
    assert bot_commands.parse(text) == command


def test_todo_lists_week_ahead_and_overdue_with_totals():
    add_payment("Аренда", TODAY - timedelta(days=3), "45000")
    add_payment("Сервер", TODAY + timedelta(days=2), "20", "USD")
    add_payment("Подписка", TODAY + timedelta(days=12), "9.99", "EUR")
    with SessionLocal() as db:
        text = bot_commands.reply(db, "todo", TODAY)
    assert text.startswith("📋 Что оплатить до 30.10.2026")
    assert "🔴 20.10 Аренда — 45 000.00 RUB (просрочен на 3 дн.)" in text
    assert "• 25.10 Сервер — 20.00 USD (через 2 дн.)" in text
    assert "Подписка" not in text  # дальше недели
    assert text.endswith("Итого: 45 000.00 RUB, 20.00 USD")


def test_overdue_and_empty_answers():
    with SessionLocal() as db:
        assert bot_commands.reply(db, "overdue", TODAY) == "Просроченных платежей нет ✅"
        assert "оплат нет" in bot_commands.reply(db, "todo", TODAY)
    add_payment("Аренда", TODAY - timedelta(days=1))
    with SessionLocal() as db:
        assert "Аренда" in bot_commands.reply(db, "overdue", TODAY)


def message(text, chat_id=tg_tests.CHAT_ID, chat_type="supergroup", user_id=10, is_bot=False):
    return {
        "update_id": 5,
        "message": {
            "message_id": 1,
            "text": text,
            "chat": {"id": chat_id, "type": chat_type},
            "from": {"id": user_id, "username": "ivan", "is_bot": is_bot},
        },
    }


def test_telegram_reminder_chat_gets_the_list():
    add_payment("Аренда", TODAY + timedelta(days=1))
    bot, api = tg_tests.make_bot()
    bot.process_update(message("/todo@aeza_invoice_keeper_bot"))
    sent = api.of("sendMessage")
    assert len(sent) == 1 and sent[0]["chat_id"] == tg_tests.CHAT_ID and "Аренда" in sent[0]["text"]


def test_telegram_foreign_group_is_ignored_and_stranger_in_private_is_refused():
    add_payment("Аренда", TODAY + timedelta(days=1))
    bot, api = tg_tests.make_bot()
    bot.process_update(message("/todo", chat_id=-777))
    assert api.of("sendMessage") == []
    bot.process_update(message("/todo", chat_id=55, chat_type="private", user_id=55))
    assert api.of("sendMessage")[-1]["text"] == bot_commands.NO_ACCESS
    bot.process_update(message("/help", chat_id=55, chat_type="private", user_id=55))
    assert api.of("sendMessage")[-1]["text"] == bot_commands.HELP


def test_telegram_linked_user_gets_the_list_in_private():
    add_payment("Аренда", TODAY - timedelta(days=2))
    link("telegram", 55, 55)
    bot, api = tg_tests.make_bot()
    bot.process_update(message("/overdue", chat_id=55, chat_type="private", user_id=55))
    assert "Аренда" in api.of("sendMessage")[-1]["text"]


def test_telegram_bots_are_ignored_and_menu_is_registered_once():
    bot, api = tg_tests.make_bot()
    bot.process_update(message("/todo", is_bot=True))
    assert api.of("sendMessage") == []
    bot.poll_once(None)
    bot.poll_once(None)
    assert api.of("setMyCommands") == [{"commands": bot_commands.MENU}]


def max_message(text, chat_id=max_tests.CHAT_ID, chat_type="chat", user_id=10, is_bot=False):
    return {
        "update_type": "message_created",
        "timestamp": 1,
        "message": {
            "recipient": {"chat_id": chat_id, "chat_type": chat_type},
            "sender": {"user_id": user_id, "is_bot": is_bot},
            "body": {"mid": "m1", "text": text},
        },
    }


def test_max_reminder_chat_and_linked_dialog_get_the_list():
    add_payment("Аренда", TODAY + timedelta(days=1))
    bot, api = max_tests.make_bot()
    bot.process_update(max_message("/todo"))
    query, body = api.of("/messages")[-1]
    assert query == {"chat_id": max_tests.CHAT_ID} and "Аренда" in body["text"]

    bot.process_update(max_message("/todo", chat_id=900, chat_type="dialog", user_id=77))
    assert api.of("/messages")[-1][1]["text"] == bot_commands.NO_ACCESS
    link("max", 77, 900)
    bot.process_update(max_message("/todo", chat_id=900, chat_type="dialog", user_id=77))
    assert "Аренда" in api.of("/messages")[-1][1]["text"]

    calls = len(api.calls)
    bot.process_update(max_message("/todo", chat_id=-5))  # чужой чат
    bot.process_update(max_message("/todo", is_bot=True))
    assert len(api.calls) == calls
