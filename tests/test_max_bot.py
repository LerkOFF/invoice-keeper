from datetime import date

import pytest

from app.core.config import Settings
from app.core.db import SessionLocal
from app.models import AuditEntry, OccurrenceStatus
from app.services.max_api import MaxError
from app.services.max_bot import MaxPayButtonBot
from tests.test_telegram_bot import REMINDER_TEXT, TODAY, new_occurrence, state

CHAT_ID = -7001


class FakeMaxApi:
    """Заглушка Bot API MAX: помнит вызовы, знает участников чата и очередь обновлений."""

    def __init__(self, members=(10,), chat_id=str(CHAT_ID), member_error=False):
        self.chat_id = chat_id
        self.members = set(members)
        self.member_error = member_error
        self.updates: list[dict] = []
        self.marker = 100
        self.calls: list[tuple[str, str, dict, dict]] = []

    def chat_id_number(self):
        try:
            return int(self.chat_id)
        except ValueError:
            raise MaxError("MAX_CHAT_ID должен быть числом") from None

    def call(self, http_method, path, *, query=None, body=None, timeout=10.0):
        self.calls.append((http_method, path, query or {}, body or {}))
        if path.endswith("/members"):
            if self.member_error:
                raise MaxError("MAX недоступен")
            user_id = int(query["user_ids"])
            return {"members": [{"user_id": user_id}] if user_id in self.members else []}
        if path == "/updates":
            batch, self.updates = self.updates, []
            self.marker += 1
            return {"updates": batch, "marker": self.marker}
        return {"success": True}

    def of(self, path):
        return [(query, body) for _, p, query, body in self.calls if p == path or p.endswith(path)]

    def answers(self):
        return [body for _, body in self.of("/answers")]


def press(occurrence_id, user_id=10, username="ivan", chat_id=CHAT_ID, chat_type="chat", callback_id="c1", payload=None):
    return {
        "update_type": "message_callback",
        "timestamp": 1,
        "callback": {
            "timestamp": 1,
            "callback_id": callback_id,
            "payload": payload if payload is not None else f"paid:{occurrence_id}",
            "user": {"user_id": user_id, "username": username, "first_name": "Иван", "is_bot": False},
        },
        "message": {
            "recipient": {"chat_id": chat_id, "chat_type": chat_type},
            "body": {"mid": "mid.1", "text": REMINDER_TEXT},
        },
    }


def make_bot(api=None, settings=None, cache_ttl=60.0, today=TODAY):
    api = api or FakeMaxApi()
    bot = MaxPayButtonBot(api, settings or Settings(), SessionLocal, today=lambda: today, cache_ttl=cache_ttl)
    return bot, api


# ---------- успешная отметка ----------


def test_chat_member_marks_payment_and_message_is_updated():
    occ = new_occurrence()
    bot, api = make_bot()

    bot.process_update(press(occ))

    assert state(occ) == (OccurrenceStatus.PAID.value, TODAY)
    [(query, body)] = api.of("/answers")
    assert query == {"callback_id": "c1"} and "отмечена" in body["notification"]
    text = body["message"]["text"]
    assert text.startswith(REMINDER_TEXT) and "Оплачено 23.10.2026" in text and "@ivan" in text
    assert body["message"]["attachments"] == []  # кнопка убрана


def test_payment_is_logged_as_max_actor():
    occ = new_occurrence()
    bot, _ = make_bot()
    bot.process_update(press(occ, username=None))
    with SessionLocal() as db:
        entry = db.query(AuditEntry).filter_by(action="occurrence.paid").one()
    assert (entry.actor_type, entry.actor, entry.details["source"]) == ("max", "Иван", "max")


def test_payment_date_is_server_today():
    occ = new_occurrence()
    bot, _ = make_bot(today=date(2026, 10, 24))
    bot.process_update(press(occ))
    assert state(occ)[1] == date(2026, 10, 24)


def test_double_press_marks_once_and_says_already():
    occ = new_occurrence()
    bot, api = make_bot()

    bot.process_update(press(occ, callback_id="c1"))
    bot.process_update(press(occ, callback_id="c2"))

    assert state(occ) == (OccurrenceStatus.PAID.value, TODAY)
    second = api.answers()[1]
    assert "Уже" in second["notification"] and "отметил(а)" not in second["message"]["text"]


# ---------- авторизация ----------


def test_non_member_is_denied():
    occ = new_occurrence()
    bot, api = make_bot(FakeMaxApi(members=()))

    bot.process_update(press(occ))

    assert state(occ)[0] == OccurrenceStatus.UNPAID.value
    [answer] = api.answers()
    assert "Нет доступа" in answer["notification"] and "message" not in answer


def test_membership_check_failure_means_denial():
    occ = new_occurrence()
    bot, api = make_bot(FakeMaxApi(member_error=True))
    bot.process_update(press(occ))
    assert state(occ)[0] == OccurrenceStatus.UNPAID.value
    assert "проверить доступ" in api.answers()[0]["notification"]


def test_allow_list_narrows_chat_members():
    api = FakeMaxApi(members=(10, 12))
    bot, _ = make_bot(api, Settings(max_allowed_user_ids="10, 11"))

    in_list_member, outsider_member, in_list_left = new_occurrence(), new_occurrence(), new_occurrence()
    bot.process_update(press(in_list_member, user_id=10))
    bot.process_update(press(outsider_member, user_id=12))
    bot.process_update(press(in_list_left, user_id=11))

    assert state(in_list_member)[0] == "paid"
    assert state(outsider_member)[0] == "unpaid"
    assert state(in_list_left)[0] == "unpaid"
    assert [q["user_ids"] for q, _ in api.of("/members")] == ["10", "11"]


def test_membership_is_cached_then_rechecked():
    api = FakeMaxApi()
    bot, _ = make_bot(api, cache_ttl=60)
    bot.process_update(press(new_occurrence(), callback_id="a"))
    bot.process_update(press(new_occurrence(), callback_id="b"))
    assert len(api.of("/members")) == 1

    api2 = FakeMaxApi()
    fresh, _ = make_bot(api2, cache_ttl=0)
    first = new_occurrence()
    fresh.process_update(press(first))
    api2.members = set()  # пользователя удалили из чата
    second = new_occurrence()
    fresh.process_update(press(second))
    assert state(first)[0] == "paid" and state(second)[0] == "unpaid"


def test_dialog_with_bot_needs_no_membership_check():
    api = FakeMaxApi(members=(), chat_id="555")
    bot, _ = make_bot(api)
    occ = new_occurrence()
    bot.process_update(press(occ, chat_id=555, chat_type="dialog"))
    assert state(occ)[0] == "paid" and api.of("/members") == []


def test_bots_cannot_press():
    occ = new_occurrence()
    bot, _ = make_bot(FakeMaxApi(members=(10,)))
    update = press(occ)
    update["callback"]["user"]["is_bot"] = True
    bot.process_update(update)
    assert state(occ)[0] == "unpaid"


def test_button_from_foreign_chat_is_ignored():
    occ = new_occurrence()
    bot, api = make_bot()
    bot.process_update(press(occ, chat_id=-777))
    assert state(occ)[0] == "unpaid" and api.of("/members") == []
    assert "другого чата" in api.answers()[0]["notification"]


def test_bad_chat_id_setting_rejects_everything():
    occ = new_occurrence()
    bot, _ = make_bot(FakeMaxApi(chat_id="@chat"))
    bot.process_update(press(occ))
    assert state(occ)[0] == "unpaid"


# ---------- некорректные данные ----------


@pytest.mark.parametrize("payload", ["", "hello", "paid:", "paid:abc", "paid:1; DROP", "paid:-3", "paid: 1", "pay:1"])
def test_garbage_payload_is_rejected(payload):
    new_occurrence()
    bot, api = make_bot()
    bot.process_update(press(1, payload=payload))
    assert "Неизвестная кнопка" in api.answers()[0]["notification"]
    assert api.of("/members") == []


def test_deleted_payment_cannot_be_marked():
    occ = new_occurrence(deleted=True)
    bot, api = make_bot()
    bot.process_update(press(occ))
    assert state(occ)[0] == "unpaid"
    assert "прекращён" in api.answers()[0]["message"]["text"]


def test_other_updates_are_ignored():
    bot, api = make_bot()
    bot.process_update({"update_type": "message_created", "message": {"body": {"text": "привет"}}})
    assert api.calls == []


def test_answer_error_does_not_break_processing():
    occ = new_occurrence()

    class OldCallback(FakeMaxApi):
        def call(self, http_method, path, **kwargs):
            if path == "/answers":
                raise MaxError("callback.expired")
            return super().call(http_method, path, **kwargs)

    bot, _ = make_bot(OldCallback())
    bot.process_update(press(occ))
    assert state(occ)[0] == "paid"


# ---------- опрос ----------


def test_poll_once_requests_callbacks_and_advances_marker():
    occ = new_occurrence()
    bot, api = make_bot()
    api.updates = [press(occ), {"update_type": "bot_added"}]

    marker = bot.poll_once(None)

    first, _ = api.of("/updates")[0]
    assert first["types"] == "message_callback,bot_started,message_created" and first["marker"] is None
    assert marker == 101 and state(occ)[0] == "paid"

    bot.poll_once(marker)
    assert api.of("/updates")[1][0]["marker"] == 101


def test_poll_keeps_marker_when_answer_has_none():
    class NoMarker(FakeMaxApi):
        def call(self, http_method, path, **kwargs):
            super().call(http_method, path, **kwargs)
            return {"updates": []}

    bot, _ = make_bot(NoMarker())
    assert bot.poll_once(55) == 55


def test_broken_update_does_not_block_the_rest():
    occ = new_occurrence()
    bot, api = make_bot()
    api.updates = [{"update_type": "message_callback", "callback": {}}, press(occ)]
    bot.poll_once(None)
    assert state(occ)[0] == "paid"


def test_poll_error_propagates_to_the_loop():
    class Down(FakeMaxApi):
        def call(self, *args, **kwargs):
            raise MaxError("сеть недоступна")

    bot, _ = make_bot(Down())
    with pytest.raises(MaxError):
        bot.poll_once(None)


# ---------- запуск вместе с приложением ----------


def test_app_starts_max_bot_only_when_configured_and_enabled(monkeypatch):
    import time

    from fastapi.testclient import TestClient

    from app import main as main_module

    def start(settings):
        polls = []

        class FakeBot:
            def poll_once(self, marker):
                polls.append(marker)
                time.sleep(0.02)
                return marker

        monkeypatch.setattr(main_module, "get_settings", lambda: settings)
        monkeypatch.setattr(main_module, "build_max_bot", lambda _s, _f: FakeBot())
        with TestClient(main_module.create_app()):
            time.sleep(0.2)
        return polls

    configured = dict(max_bot_token="T", max_chat_id="-1", scheduler_enabled=False, telegram_buttons_enabled=False)
    assert len(start(Settings(**configured, max_buttons_enabled=True))) >= 2
    assert start(Settings(**configured, max_buttons_enabled=False)) == []
    assert start(Settings(scheduler_enabled=False, max_buttons_enabled=True)) == []
