import asyncio
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.core.config import Settings
from app.core.db import SessionLocal
from app.models import OccurrenceStatus, PaymentOccurrence, RecurringPayment
from app.services import telegram_bot
from app.services.periods import ensure_occurrences
from app.services.telegram import TelegramError
from app.services.telegram_bot import PayButtonBot, bot_loop

TODAY = date(2026, 10, 23)
CHAT_ID = -1001
REMINDER_TEXT = "🔔 Напоминание об оплате\n\nПлатёж: Аренда\nСумма: 100.00 RUB"


class FakeBotApi:
    """Заглушка Bot API: помнит вызовы, знает участников чата и очередь обновлений."""

    def __init__(self, members=None, chat_id=str(CHAT_ID), member_error=False):
        self.chat_id = chat_id
        self.members = members or {}
        self.member_error = member_error
        self.updates: list[dict] = []
        self.calls: list[tuple[str, dict]] = []

    def call(self, method, payload=None, *, timeout=10.0):
        self.calls.append((method, payload or {}))
        if method == "getChatMember":
            if self.member_error:
                raise TelegramError("Telegram недоступен")
            return self.members.get(payload["user_id"], {"status": "left"})
        if method == "getUpdates":
            batch, self.updates = self.updates, []
            return batch
        return True

    def of(self, method):
        return [payload for name, payload in self.calls if name == method]


def new_occurrence(due=TODAY + timedelta(days=1), deleted=False) -> int:
    with SessionLocal() as db:
        payment = RecurringPayment(name="Аренда", currency="RUB", first_due_date=due)
        payment.amount = Decimal("100")
        db.add(payment)
        db.flush()
        ensure_occurrences(db, payment, TODAY)
        if deleted:  # платёж прекращают уже после появления периода, как в жизни
            payment.deleted_at = datetime.now(UTC)
        db.commit()
        return payment.occurrences[0].id


def state(occurrence_id: int):
    with SessionLocal() as db:
        o = db.get(PaymentOccurrence, occurrence_id)
        return o.status, o.paid_at


def press(occurrence_id, user_id=10, username="ivan", chat=None, query_id="q1", data=None, text=REMINDER_TEXT):
    return {
        "update_id": 1,
        "callback_query": {
            "id": query_id,
            "from": {"id": user_id, "username": username, "first_name": "Иван"},
            "message": {"message_id": 7, "text": text, "chat": chat or {"id": CHAT_ID, "type": "supergroup"}},
            "data": data if data is not None else f"paid:{occurrence_id}",
        },
    }


def make_bot(api=None, settings=None, cache_ttl=60.0, today=TODAY):
    api = api or FakeBotApi(members={10: {"status": "member"}})
    bot = PayButtonBot(api, settings or Settings(), SessionLocal, today=lambda: today, cache_ttl=cache_ttl)
    return bot, api


# ---------- успешная отметка ----------


def test_chat_member_marks_payment_and_message_is_updated():
    occ = new_occurrence()
    bot, api = make_bot()

    bot.process_update(press(occ))

    assert state(occ) == (OccurrenceStatus.PAID.value, TODAY)
    answer = api.of("answerCallbackQuery")[0]
    assert answer["callback_query_id"] == "q1" and "отмечена" in answer["text"] and not answer["show_alert"]
    edit = api.of("editMessageText")[0]
    assert edit["chat_id"] == CHAT_ID and edit["message_id"] == 7
    assert edit["text"].startswith(REMINDER_TEXT) and "Оплачено 23.10.2026" in edit["text"] and "@ivan" in edit["text"]
    assert edit["reply_markup"] == {"inline_keyboard": []}


def test_payment_date_is_server_today():
    occ = new_occurrence()
    bot, _ = make_bot(today=date(2026, 10, 24))
    bot.process_update(press(occ))
    assert state(occ)[1] == date(2026, 10, 24)


def test_user_without_username_is_shown_by_name():
    occ = new_occurrence()
    bot, api = make_bot()
    bot.process_update(press(occ, username=None))
    assert "Иван" in api.of("editMessageText")[0]["text"]


def test_double_press_marks_once_and_says_already():
    occ = new_occurrence()
    bot, api = make_bot()

    bot.process_update(press(occ, query_id="q1"))
    bot.process_update(press(occ, query_id="q2"))

    assert state(occ) == (OccurrenceStatus.PAID.value, TODAY)
    assert "Уже" in api.of("answerCallbackQuery")[1]["text"]
    assert "отметил(а)" not in api.of("editMessageText")[1]["text"]


def test_button_after_payment_marked_in_panel_keeps_panel_date():
    occ = new_occurrence()
    with SessionLocal() as db:
        o = db.get(PaymentOccurrence, occ)
        o.status, o.paid_at = OccurrenceStatus.PAID.value, date(2026, 10, 20)
        db.commit()
    bot, api = make_bot()

    bot.process_update(press(occ))

    assert state(occ) == (OccurrenceStatus.PAID.value, date(2026, 10, 20))
    assert "20.10.2026" in api.of("editMessageText")[0]["text"]


# ---------- авторизация по списку чата ----------


@pytest.mark.parametrize("status", ["left", "kicked"])
def test_non_member_is_denied(status):
    occ = new_occurrence()
    bot, api = make_bot(FakeBotApi(members={10: {"status": status}}))

    bot.process_update(press(occ))

    assert state(occ)[0] == OccurrenceStatus.UNPAID.value
    answer = api.of("answerCallbackQuery")[0]
    assert answer["show_alert"] and "Нет доступа" in answer["text"]
    assert api.of("editMessageText") == []


def test_stranger_unknown_to_chat_is_denied():
    occ = new_occurrence()
    bot, _ = make_bot(FakeBotApi(members={}))
    bot.process_update(press(occ, user_id=999))
    assert state(occ)[0] == OccurrenceStatus.UNPAID.value


@pytest.mark.parametrize(
    ("member", "allowed"),
    [
        ({"status": "member"}, True),
        ({"status": "administrator"}, True),
        ({"status": "creator"}, True),
        ({"status": "restricted", "is_member": True}, True),
        ({"status": "restricted", "is_member": False}, False),
    ],
)
def test_membership_statuses(member, allowed):
    occ = new_occurrence()
    bot, _ = make_bot(FakeBotApi(members={10: member}))
    bot.process_update(press(occ))
    assert (state(occ)[0] == OccurrenceStatus.PAID.value) is allowed


def test_membership_check_failure_means_denial():
    occ = new_occurrence()
    bot, api = make_bot(FakeBotApi(member_error=True))

    bot.process_update(press(occ))

    assert state(occ)[0] == OccurrenceStatus.UNPAID.value
    assert "проверить доступ" in api.of("answerCallbackQuery")[0]["text"]


def test_allow_list_narrows_chat_members():
    settings = Settings(telegram_allowed_user_ids="10, 11")
    api = FakeBotApi(members={10: {"status": "member"}, 12: {"status": "member"}, 11: {"status": "left"}})
    bot, _ = make_bot(api, settings)

    in_list_member, outsider_member, in_list_left = new_occurrence(), new_occurrence(), new_occurrence()
    bot.process_update(press(in_list_member, user_id=10))
    bot.process_update(press(outsider_member, user_id=12))
    bot.process_update(press(in_list_left, user_id=11))

    assert state(in_list_member)[0] == OccurrenceStatus.PAID.value
    assert state(outsider_member)[0] == OccurrenceStatus.UNPAID.value  # участник, но не в списке
    assert state(in_list_left)[0] == OccurrenceStatus.UNPAID.value  # в списке, но не участник
    assert [c["user_id"] for c in api.of("getChatMember")] == [10, 11]  # не из списка отсекается без запроса


def test_membership_is_cached_then_rechecked():
    api = FakeBotApi(members={10: {"status": "member"}})
    bot, _ = make_bot(api, cache_ttl=60)
    bot.process_update(press(new_occurrence(), query_id="a"))
    bot.process_update(press(new_occurrence(), query_id="b"))
    assert len(api.of("getChatMember")) == 1

    api2 = FakeBotApi(members={10: {"status": "member"}})
    fresh, _ = make_bot(api2, cache_ttl=0)
    first = new_occurrence()
    fresh.process_update(press(first))
    api2.members = {}  # пользователя удалили из чата
    second = new_occurrence()
    fresh.process_update(press(second))
    assert state(first)[0] == "paid" and state(second)[0] == "unpaid"


def test_private_chat_allows_only_its_owner():
    api = FakeBotApi(chat_id="10")
    bot, _ = make_bot(api)
    private = {"id": 10, "type": "private"}

    owner, other = new_occurrence(), new_occurrence()
    bot.process_update(press(owner, user_id=10, chat=private))
    bot.process_update(press(other, user_id=11, chat=private))

    assert state(owner)[0] == "paid" and state(other)[0] == "unpaid"
    assert api.of("getChatMember") == []


def test_button_from_foreign_chat_is_ignored():
    occ = new_occurrence()
    bot, api = make_bot()

    bot.process_update(press(occ, chat={"id": -777, "type": "supergroup"}))

    assert state(occ)[0] == "unpaid" and api.of("getChatMember") == []
    assert "другого чата" in api.of("answerCallbackQuery")[0]["text"]


def test_chat_configured_by_username():
    occ = new_occurrence()
    api = FakeBotApi(members={10: {"status": "member"}}, chat_id="@MyChat")
    bot, _ = make_bot(api)
    bot.process_update(press(occ, chat={"id": -5, "type": "supergroup", "username": "mychat"}))
    assert state(occ)[0] == "paid"


# ---------- некорректные данные ----------


@pytest.mark.parametrize("data", ["", "hello", "paid:", "paid:abc", "paid:1; DROP", "paid:-3", "paid: 1", "pay:1"])
def test_garbage_callback_data_is_rejected(data):
    new_occurrence()
    bot, api = make_bot()
    bot.process_update(press(1, data=data))
    assert "Неизвестная кнопка" in api.of("answerCallbackQuery")[0]["text"]
    assert api.of("getChatMember") == []


def test_deleted_payment_cannot_be_marked():
    occ = new_occurrence(deleted=True)
    bot, api = make_bot()

    bot.process_update(press(occ))

    assert state(occ)[0] == "unpaid"
    assert api.of("answerCallbackQuery")[0]["show_alert"]
    assert "прекращён" in api.of("editMessageText")[0]["text"]


def test_unknown_period_is_reported():
    bot, api = make_bot()
    bot.process_update(press(99999))
    assert "не найден" in api.of("answerCallbackQuery")[0]["text"]


def test_non_callback_updates_are_ignored():
    bot, api = make_bot()
    bot.process_update({"update_id": 5, "message": {"text": "привет"}})
    assert api.calls == []


def test_old_query_error_does_not_break_processing():
    occ = new_occurrence()

    class OldQueryApi(FakeBotApi):
        def call(self, method, payload=None, *, timeout=10.0):
            if method == "answerCallbackQuery":
                raise TelegramError("query is too old")
            return super().call(method, payload, timeout=timeout)

    bot, _ = make_bot(OldQueryApi(members={10: {"status": "member"}}))
    bot.process_update(press(occ))
    assert state(occ)[0] == "paid"


# ---------- опрос ----------


def test_poll_once_requests_callbacks_and_advances_offset():
    occ = new_occurrence()
    bot, api = make_bot()
    api.updates = [press(occ) | {"update_id": 41}, {"update_id": 42, "message": {}}]

    offset = bot.poll_once(None)

    first = api.of("getUpdates")[0]
    assert first["allowed_updates"] == ["callback_query", "message"] and "offset" not in first
    assert offset == 43 and state(occ)[0] == "paid"

    bot.poll_once(offset)
    assert api.of("getUpdates")[1]["offset"] == 43


def test_broken_update_does_not_block_the_rest():
    occ = new_occurrence()
    bot, api = make_bot()
    api.updates = [{"update_id": 1, "callback_query": {}}, press(occ) | {"update_id": 2}]

    assert bot.poll_once(None) == 3
    assert state(occ)[0] == "paid"


def test_poll_error_propagates_to_the_loop():
    class Down(FakeBotApi):
        def call(self, method, payload=None, *, timeout=10.0):
            raise TelegramError("Telegram отклонил запрос getUpdates: Conflict (код 409)")

    bot, _ = make_bot(Down())
    with pytest.raises(TelegramError):
        bot.poll_once(None)


# ---------- цикл ----------


def test_loop_survives_errors_and_keeps_polling(monkeypatch):
    real_sleep = asyncio.sleep
    monkeypatch.setattr(telegram_bot.asyncio, "sleep", lambda _s: real_sleep(0.001))
    calls = []

    class Flaky:
        def poll_once(self, offset):
            calls.append(offset)
            if len(calls) == 1:
                raise TelegramError("сеть недоступна")
            if len(calls) == 2:
                raise RuntimeError("неожиданный сбой")
            return (offset or 0) + 1

    async def scenario():
        task = asyncio.create_task(bot_loop(Flaky()))
        await real_sleep(0.2)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    asyncio.run(scenario())
    assert len(calls) >= 5 and calls[2:5] == [None, 1, 2]  # после двух сбоев offset продолжает расти


# ---------- запуск вместе с приложением ----------


def _start_app(monkeypatch, settings):
    from fastapi.testclient import TestClient

    from app import main as main_module

    polls = []

    class FakeBot:
        def poll_once(self, offset):
            polls.append(offset)
            import time

            time.sleep(0.02)
            return offset

    monkeypatch.setattr(main_module, "get_settings", lambda: settings)
    monkeypatch.setattr(main_module, "build_bot", lambda _s, _f: FakeBot())
    with TestClient(main_module.create_app()):
        import time

        time.sleep(0.2)
    return polls


def test_app_starts_bot_only_when_telegram_configured_and_enabled(monkeypatch):
    configured = dict(telegram_bot_token="1:T", telegram_chat_id="-1", scheduler_enabled=False)

    assert len(_start_app(monkeypatch, Settings(**configured, telegram_buttons_enabled=True))) >= 2
    assert _start_app(monkeypatch, Settings(**configured, telegram_buttons_enabled=False)) == []
    assert _start_app(monkeypatch, Settings(scheduler_enabled=False, telegram_buttons_enabled=True)) == []


def test_state_helper_reads_db():
    occ = new_occurrence()
    assert state(occ) == (OccurrenceStatus.UNPAID.value, None)
    with SessionLocal() as db:
        assert db.scalar(select(PaymentOccurrence.id)) == occ
