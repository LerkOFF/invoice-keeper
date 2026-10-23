import json

import httpx
import pytest

from app.core.config import Settings
from app.services.max_api import MaxError, MaxNotifier, discover_chats, tls_context
from app.services.notify import Reminder
from app.services.telegram import build_notifiers

TOKEN = "max-SECRET-TOKEN-VALUE"


def make(handler, **overrides) -> MaxNotifier:
    settings = Settings(**({"max_bot_token": TOKEN, "max_chat_id": "-7001", "max_buttons_enabled": True} | overrides))
    return MaxNotifier(settings, transport=httpx.MockTransport(handler))


def capture(seen):
    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(
            method=request.method,
            url=request.url,
            auth=request.headers.get("Authorization"),
            body=json.loads(request.content) if request.content else None,
        )
        return httpx.Response(200, json={"message": {"body": {"mid": "m1"}}})

    return handler


def test_sends_message_with_pay_button_to_chat():
    seen = {}
    make(capture(seen)).send_text("привет", pay_button_for=42)

    assert seen["method"] == "POST" and seen["url"].path == "/messages"
    assert seen["url"].host == "platform-api2.max.ru" and seen["url"].params["chat_id"] == "-7001"
    assert seen["auth"] == TOKEN and TOKEN not in str(seen["url"])  # токен только в заголовке
    assert seen["body"]["text"] == "привет"
    [keyboard] = seen["body"]["attachments"]
    assert keyboard["type"] == "inline_keyboard"
    assert keyboard["payload"]["buttons"] == [[{"type": "callback", "text": "✅ Оплачено", "payload": "paid:42"}]]


def test_reminder_goes_with_button_and_without_when_disabled():
    reminder = Reminder(1, 1, "Аренда", 0, "RUB", None, 1, "текст")  # type: ignore[arg-type]
    seen = {}
    make(capture(seen)).send(reminder)
    assert seen["body"]["attachments"][0]["payload"]["buttons"][0][0]["payload"] == "paid:1"

    make(capture(seen), max_buttons_enabled=False).send(reminder)
    assert "attachments" not in seen["body"]


def test_custom_api_base():
    seen = {}
    make(capture(seen), max_api_base="http://fake-max:8082/").send_text("x")
    assert str(seen["url"]).startswith("http://fake-max:8082/messages")


def test_not_configured():
    notifier = MaxNotifier(Settings(max_bot_token="", max_chat_id=""))
    assert notifier.configured is False
    with pytest.raises(MaxError):
        notifier.send_text("x")


def test_half_configured_is_not_configured():
    assert MaxNotifier(Settings(max_bot_token=TOKEN, max_chat_id="")).configured is False
    assert MaxNotifier(Settings(max_bot_token="", max_chat_id="-1")).configured is False


def test_chat_id_must_be_a_number():
    notifier = make(capture({}), max_chat_id="@chat")
    with pytest.raises(MaxError) as error:
        notifier.send_text("x")
    assert "числом" in str(error.value)


@pytest.mark.parametrize(
    ("status", "body", "expected"),
    [
        (401, {"code": "verify.token", "message": "Invalid access_token"}, "Invalid access_token"),
        (404, {"code": "chat.not.found"}, "chat.not.found"),
        (200, {"success": False, "message": "message.too.old"}, "message.too.old"),
    ],
)
def test_max_rejection_is_an_error_without_token(status, body, expected):
    with pytest.raises(MaxError) as error:
        make(lambda _r: httpx.Response(status, json=body)).send_text("x")
    assert expected in str(error.value) and TOKEN not in str(error.value)


def test_network_error_hides_token():
    def handler(request):
        raise httpx.ConnectError(f"failed {request.headers['Authorization']}")

    with pytest.raises(MaxError) as error:
        make(handler).send_text("x")
    assert "сеть недоступна" in str(error.value) and TOKEN not in str(error.value)


def test_non_json_answer():
    with pytest.raises(MaxError) as error:
        make(lambda _r: httpx.Response(502, text="<html>")).send_text("x")
    assert "не JSON" in str(error.value)


def test_discover_chats_from_events_needs_only_token():
    updates = [
        {"update_type": "bot_added", "chat_id": -5, "user": {"first_name": "Аня"}},
        {"update_type": "message_created", "message": {"recipient": {"chat_id": -5, "chat_type": "chat"}}},
        {"update_type": "bot_started", "chat_id": 77, "user": {"first_name": "Иван"}},
        {"update_type": "message_created", "message": {}},
    ]
    seen = {}

    def handler(request):
        seen["params"] = dict(request.url.params)
        return httpx.Response(200, json={"updates": updates, "marker": 1})

    chats = discover_chats(make(handler, max_chat_id=""))
    assert [(c["chat_id"], c["type"]) for c in chats] == [(-5, "chat"), (77, "dialog")]
    assert seen["params"]["types"] == "bot_added,bot_started,message_created"


def test_tls_context_trusts_russian_ca():
    names = {dict(item[0] for item in cert["subject"]).get("commonName") for cert in tls_context().get_ca_certs()}
    assert {"Russian Trusted Root CA", "Russian Trusted Sub CA"} <= names


def test_max_is_one_of_reminder_channels():
    names = [n.name for n in build_notifiers(Settings())]
    assert names == ["telegram", "max", "email", "webhook"]
    configured = {n.name for n in build_notifiers(Settings(max_bot_token=TOKEN, max_chat_id="-1")) if n.configured}
    assert configured == {"max"}
