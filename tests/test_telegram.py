import json

import httpx
import pytest

from app.core.config import Settings
from app.services.telegram import TelegramError, TelegramNotifier

TOKEN = "123456:SECRET-TOKEN-VALUE"


def make(handler, **overrides) -> TelegramNotifier:
    settings = Settings(telegram_bot_token=TOKEN, telegram_chat_id="-1001", **overrides)
    return TelegramNotifier(settings, transport=httpx.MockTransport(handler))


def test_sends_message_to_bot_api():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"ok": True, "result": {}})

    make(handler).send("привет")

    assert seen["url"] == f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    assert seen["body"]["chat_id"] == "-1001" and seen["body"]["text"] == "привет"


def test_custom_api_base():
    seen = {}
    make(
        lambda r: seen.update(url=str(r.url)) or httpx.Response(200, json={"ok": True}),
        telegram_api_base="http://fake-telegram:8081/",
    ).send("x")
    assert seen["url"].startswith("http://fake-telegram:8081/bot")


def test_not_configured():
    notifier = TelegramNotifier(Settings(telegram_bot_token="", telegram_chat_id=""))
    assert notifier.configured is False
    with pytest.raises(TelegramError):
        notifier.send("x")


def test_half_configured_is_not_configured():
    assert TelegramNotifier(Settings(telegram_bot_token=TOKEN, telegram_chat_id="")).configured is False
    assert TelegramNotifier(Settings(telegram_bot_token="", telegram_chat_id="1")).configured is False


def test_telegram_rejection_is_an_error_without_token():
    def handler(_):
        return httpx.Response(400, json={"ok": False, "description": "Bad Request: chat not found"})

    with pytest.raises(TelegramError) as error:
        make(handler).send("x")
    assert "chat not found" in str(error.value) and TOKEN not in str(error.value)


def test_rate_limit_is_an_error():
    def handler(_):
        return httpx.Response(429, json={"ok": False, "description": "Too Many Requests"})

    with pytest.raises(TelegramError, match="429"):
        make(handler).send("x")


def test_network_failure_does_not_leak_token():
    def handler(request):
        raise httpx.ConnectError(f"cannot connect to {request.url}")

    with pytest.raises(TelegramError) as error:
        make(handler).send("x")
    assert TOKEN not in str(error.value) and "ConnectError" in str(error.value)


def test_non_json_response():
    with pytest.raises(TelegramError, match="не JSON"):
        make(lambda _: httpx.Response(502, text="<html>bad gateway</html>")).send("x")


def test_reminder_message_carries_pay_button():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"ok": True, "result": {}})

    make(handler, telegram_buttons_enabled=True).send("напоминание", pay_button_for=42)

    markup = seen["body"]["reply_markup"]["inline_keyboard"]
    assert markup == [[{"text": "✅ Оплачено", "callback_data": "paid:42"}]]


def test_no_button_without_period_or_when_disabled():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return httpx.Response(200, json={"ok": True, "result": {}})

    make(handler, telegram_buttons_enabled=True).send("без кнопки")
    make(handler, telegram_buttons_enabled=False).send("кнопки выключены", pay_button_for=7)

    assert all("reply_markup" not in body for body in seen)


def test_call_returns_result_field():
    notifier = make(lambda _: httpx.Response(200, json={"ok": True, "result": [{"update_id": 1}]}))
    assert notifier.call("getUpdates") == [{"update_id": 1}]
