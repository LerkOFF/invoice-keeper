from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.core.config import Settings, get_settings
from app.core.db import SessionLocal
from app.models import AuditEntry, MessengerLink, MessengerLinkCode, ReminderDelivery
from app.services import links
from app.services.notify import NotifyError
from app.services.reminders import send_due_reminders
from app.services.telegram_bot import PayButtonBot
from app.services.max_bot import MaxPayButtonBot
from tests.conftest import logged_in
from tests.fakes import FakeNotifier
from tests.helpers import ADMIN, B, TODAY, USER
from tests.test_max_bot import FakeMaxApi
from tests.test_telegram_bot import FakeBotApi, new_occurrence, state

BOTS = Settings(
    telegram_bot_token="1:T", telegram_chat_id="-1001", max_bot_token="m-token", max_chat_id="-7001",
    telegram_buttons_enabled=True, max_buttons_enabled=True,
)


@pytest.fixture(autouse=True)
def bot_names(monkeypatch):
    monkeypatch.setattr(links, "_bot_usernames", {"telegram": "keeper_bot", "max": "keeper_max_bot"})


@pytest.fixture
def bots_app(app):
    app.dependency_overrides[get_settings] = lambda: BOTS
    return app


def get_code(client, messenger="telegram") -> str:
    response = client.post(f"{B}/me/messengers/{messenger}/link")
    assert response.status_code == 200, response.text
    return response.json()["command"].split()[1]


def tg_bot(api=None):
    api = api or FakeBotApi(members={10: {"status": "member"}})
    return PayButtonBot(api, BOTS, SessionLocal, today=lambda: TODAY), api


def tg_start(bot, code, user_id=10, username="ivan_tg", chat_type="private"):
    chat_id = user_id if chat_type == "private" else -1001
    bot.process_update(
        {"update_id": 1, "message": {"message_id": 1, "text": f"/start {code}".strip(), "from": {"id": user_id, "username": username, "first_name": "Иван"}, "chat": {"id": chat_id, "type": chat_type}}}
    )


def all_links():
    with SessionLocal() as db:
        return [(l.messenger, l.user_id, l.is_admin, l.external_user_id, l.chat_id, l.display_name) for l in db.scalars(select(MessengerLink))]


def user_id(login):
    from app.models import User

    with SessionLocal() as db:
        return db.scalar(select(User.id).where(User.login == login))


# ---------- API ----------


def test_status_shows_bots_unavailable_without_tokens(user):
    body = user.get(f"{B}/me/messengers").json()
    assert [(m["messenger"], m["available"], m["linked"]) for m in body] == [("telegram", False, False), ("max", False, False)]
    assert user.post(f"{B}/me/messengers/telegram/link").status_code == 503


def test_messengers_need_login(anon):
    assert anon.get(f"{B}/me/messengers").status_code == 401
    assert anon.post(f"{B}/me/messengers/telegram/link").status_code == 401
    assert anon.delete(f"{B}/me/messengers/telegram").status_code == 401


def test_link_returns_deep_links_and_command(bots_app):
    client = logged_in(bots_app, USER)
    tg = client.post(f"{B}/me/messengers/telegram/link").json()
    mx = client.post(f"{B}/me/messengers/max/link").json()
    code = tg["command"].split()[1]
    assert tg["url"] == f"https://t.me/keeper_bot?start={code}" and tg["command"] == f"/start {code}"
    assert mx["url"].startswith("https://max.ru/keeper_max_bot?start=")
    assert tg["expires_at"].endswith("Z")
    assert client.post(f"{B}/me/messengers/vk/link").status_code == 422
    with SessionLocal() as db:
        stored = db.scalars(select(MessengerLinkCode.code_hash)).all()
    assert code not in stored  # в базе только хэш
    client.__exit__(None, None, None)


def test_unknown_bot_name_still_gives_command(bots_app, monkeypatch):
    monkeypatch.setattr(links, "_bot_usernames", {})
    monkeypatch.setattr(links, "bot_username", lambda *_a, **_k: (_ for _ in ()).throw(NotifyError("нет имени")))
    client = logged_in(bots_app, USER)
    body = client.post(f"{B}/me/messengers/telegram/link").json()
    assert body["url"] is None and body["command"].startswith("/start ")
    client.__exit__(None, None, None)


# ---------- привязка в Telegram ----------


def test_start_with_code_links_account_to_user(bots_app):
    client = logged_in(bots_app, USER)
    bot, api = tg_bot()
    tg_start(bot, get_code(client))

    assert all_links() == [("telegram", user_id("ivan"), False, "10", "10", "@ivan_tg")]
    assert "Готово" in api.of("sendMessage")[0]["text"] and "ivan" in api.of("sendMessage")[0]["text"]
    status = client.get(f"{B}/me/messengers").json()[0]
    assert status["linked"] and status["account"] == "@ivan_tg" and status["linked_at"]
    with SessionLocal() as db:
        entry = db.scalar(select(AuditEntry).where(AuditEntry.action == "messenger.link"))
    assert entry.actor == "ivan" and entry.details["messenger"] == "telegram"
    client.__exit__(None, None, None)


def test_code_is_one_time_and_new_code_cancels_old(bots_app):
    client = logged_in(bots_app, USER)
    bot, api = tg_bot()
    first = get_code(client)
    second = get_code(client)
    tg_start(bot, first)  # старый код сгорел
    assert all_links() == [] and "не подошёл" in api.of("sendMessage")[-1]["text"]
    tg_start(bot, second)
    tg_start(bot, second, user_id=11)  # повторно тем же кодом нельзя
    assert [l[3] for l in all_links()] == ["10"]
    client.__exit__(None, None, None)


def test_expired_code_is_rejected(bots_app):
    client = logged_in(bots_app, USER)
    code = get_code(client)
    with SessionLocal() as db:
        db.scalar(select(MessengerLinkCode)).expires_at = datetime.now(UTC) - timedelta(seconds=1)
        db.commit()
    bot, api = tg_bot()
    tg_start(bot, code)
    assert all_links() == [] and "устарела" in api.of("sendMessage")[0]["text"]
    client.__exit__(None, None, None)


def test_garbage_code_and_plain_start(bots_app):
    bot, api = tg_bot()
    tg_start(bot, "nonsense-code")
    tg_start(bot, "")
    texts = [c["text"] for c in api.of("sendMessage")]
    assert "не подошёл" in texts[0] and "«Мессенджеры»" in texts[1]
    assert all_links() == []


def test_codes_in_groups_are_ignored(bots_app):
    client = logged_in(bots_app, USER)
    bot, api = tg_bot()
    tg_start(bot, get_code(client), chat_type="supergroup")
    assert all_links() == [] and api.of("sendMessage") == []
    client.__exit__(None, None, None)


def test_code_for_telegram_does_not_work_in_max(bots_app):
    client = logged_in(bots_app, USER)
    code = get_code(client, "telegram")
    api = FakeMaxApi()
    MaxPayButtonBot(api, BOTS, SessionLocal, today=lambda: TODAY).process_update(
        {"update_type": "bot_started", "chat_id": 555, "user": {"user_id": 10, "first_name": "Иван"}, "payload": code}
    )
    assert all_links() == []
    client.__exit__(None, None, None)


def test_relinking_moves_account_and_replaces_previous(bots_app):
    admin_client = logged_in(bots_app, ADMIN)
    admin_client.post(f"{B}/users", json={"login": "olga", "password": "olga-pass-123"})
    ivan = logged_in(bots_app, USER)
    olga = logged_in(bots_app, {"login": "olga", "password": "olga-pass-123"})
    bot, _ = tg_bot()

    tg_start(bot, get_code(ivan), user_id=10)
    tg_start(bot, get_code(ivan), user_id=20, username="ivan_new")  # второй аккаунт ivan заменяет первый
    assert [(l[1], l[3]) for l in all_links()] == [(user_id("ivan"), "20")]

    tg_start(bot, get_code(olga), user_id=20, username="shared")  # аккаунт переезжает к olga
    assert [(l[1], l[3]) for l in all_links()] == [(user_id("olga"), "20")]
    assert ivan.get(f"{B}/me/messengers").json()[0]["linked"] is False
    for c in (admin_client, ivan, olga):
        c.__exit__(None, None, None)


def test_admin_can_link_too_and_unlink(bots_app):
    client = logged_in(bots_app, ADMIN)
    bot, _ = tg_bot()
    tg_start(bot, get_code(client), user_id=99, username="boss_tg")
    assert all_links() == [("telegram", None, True, "99", "99", "@boss_tg")]

    assert client.delete(f"{B}/me/messengers/telegram").status_code == 204
    assert all_links() == []
    assert client.delete(f"{B}/me/messengers/telegram").status_code == 404
    with SessionLocal() as db:
        assert db.scalar(select(AuditEntry.actor).where(AuditEntry.action == "messenger.unlink")) == "boss"
    client.__exit__(None, None, None)


def test_deleting_user_removes_links_and_list_shows_messengers(bots_app):
    admin_client = logged_in(bots_app, ADMIN)
    ivan = logged_in(bots_app, USER)
    bot, _ = tg_bot()
    tg_start(bot, get_code(ivan))
    listed = {u["login"]: u["messengers"] for u in admin_client.get(f"{B}/users").json()}
    assert listed["ivan"] == ["telegram"]

    admin_client.delete(f"{B}/users/{user_id('ivan')}")
    assert all_links() == []
    for c in (admin_client, ivan):
        c.__exit__(None, None, None)


# ---------- привязка в MAX ----------


def test_max_start_button_and_command_link_account(bots_app):
    client = logged_in(bots_app, USER)
    api = FakeMaxApi()
    bot = MaxPayButtonBot(api, BOTS, SessionLocal, today=lambda: TODAY)
    bot.process_update({"update_type": "bot_started", "chat_id": 555, "user": {"user_id": 7, "username": "ivan_max"}, "payload": get_code(client, "max")})
    assert all_links() == [("max", user_id("ivan"), False, "7", "555", "@ivan_max")]
    assert "Готово" in api.of("/messages")[0][1]["text"] and api.of("/messages")[0][0]["chat_id"] == 555

    client.delete(f"{B}/me/messengers/max")
    bot.process_update(
        {"update_type": "message_created", "message": {"sender": {"user_id": 7, "first_name": "Иван"}, "recipient": {"chat_id": 556, "chat_type": "dialog"}, "body": {"text": f"/start {get_code(client, 'max')}"}}}
    )
    assert all_links() == [("max", user_id("ivan"), False, "7", "556", "Иван")]
    client.__exit__(None, None, None)


# ---------- кнопка в личке ----------


def link_directly(messenger="telegram", external="10", chat="10", login="ivan"):
    with SessionLocal() as db:
        db.add(MessengerLink(messenger=messenger, user_id=user_id(login), is_admin=False, external_user_id=external, chat_id=chat, display_name="@ivan_tg"))
        db.commit()


def test_linked_user_pays_from_private_chat_as_panel_user():
    link_directly()
    occ = new_occurrence()
    bot, api = tg_bot(FakeBotApi(members={}))  # в общем чате он даже не состоит
    bot.process_update(
        {"update_id": 1, "callback_query": {"id": "q", "from": {"id": 10, "username": "ivan_tg"}, "data": f"paid:{occ}", "message": {"message_id": 3, "text": "напоминание", "chat": {"id": 10, "type": "private"}}}}
    )
    assert state(occ)[0] == "paid"
    assert "ivan (@ivan_tg)" in api.of("editMessageText")[0]["text"]
    assert api.of("getChatMember") == []
    with SessionLocal() as db:
        entry = db.scalar(select(AuditEntry).where(AuditEntry.action == "occurrence.paid"))
    assert (entry.actor_type, entry.actor, entry.details["source"]) == ("user", "ivan", "telegram")


def test_unlinked_private_chat_button_is_rejected():
    occ = new_occurrence()
    bot, api = tg_bot()
    bot.process_update(
        {"update_id": 1, "callback_query": {"id": "q", "from": {"id": 10}, "data": f"paid:{occ}", "message": {"message_id": 3, "text": "x", "chat": {"id": 10, "type": "private"}}}}
    )
    assert state(occ)[0] == "unpaid" and "другого чата" in api.of("answerCallbackQuery")[0]["text"]


def test_someone_elses_private_chat_cannot_be_used():
    link_directly(chat="10")
    occ = new_occurrence()
    bot, _ = tg_bot()
    bot.process_update(
        {"update_id": 1, "callback_query": {"id": "q", "from": {"id": 10}, "data": f"paid:{occ}", "message": {"message_id": 3, "text": "x", "chat": {"id": 77, "type": "private"}}}}
    )
    assert state(occ)[0] == "unpaid"


def test_linked_user_in_group_is_logged_as_panel_user():
    link_directly()
    occ = new_occurrence()
    bot, _ = tg_bot()
    bot.process_update(
        {"update_id": 1, "callback_query": {"id": "q", "from": {"id": 10, "username": "ivan_tg"}, "data": f"paid:{occ}", "message": {"message_id": 3, "text": "x", "chat": {"id": -1001, "type": "supergroup"}}}}
    )
    with SessionLocal() as db:
        assert db.scalar(select(AuditEntry.actor).where(AuditEntry.action == "occurrence.paid")) == "ivan"


def test_max_dialog_button_for_linked_user():
    link_directly("max", external="7", chat="555")
    occ = new_occurrence()
    api = FakeMaxApi(members=())
    MaxPayButtonBot(api, BOTS, SessionLocal, today=lambda: TODAY).process_update(
        {"update_type": "message_callback", "callback": {"callback_id": "c", "payload": f"paid:{occ}", "user": {"user_id": 7, "first_name": "Иван", "is_bot": False}}, "message": {"recipient": {"chat_id": 555, "chat_type": "dialog"}, "body": {"text": "напоминание"}}}
    )
    assert state(occ)[0] == "paid"
    assert "ivan" in api.answers()[0]["message"]["text"]


# ---------- личные напоминания ----------


class FakeDM:
    def __init__(self, fail: str | None = None):
        self.sent: list[tuple] = []
        self.fail = fail

    def call(self, *args, **kwargs):
        if self.fail:
            raise NotifyError(self.fail)
        self.sent.append((args, kwargs))
        return {"ok": True}


@pytest.fixture
def dm(monkeypatch):
    fake = FakeDM()
    monkeypatch.setattr(links.PersonalNotifier, "_client", lambda self: fake)
    return fake


def run(shared=None):
    with SessionLocal() as db:
        return send_due_reminders(db, [shared or FakeNotifier()], BOTS, TODAY)


def deliveries():
    with SessionLocal() as db:
        return sorted(db.scalars(select(ReminderDelivery.channel)))


def test_each_linked_user_gets_a_personal_reminder_once(dm):
    from app.models import User
    from app.core.security import hash_password

    with SessionLocal() as db:
        db.add(User(login="olga", password_hash=hash_password("olga-pass-123")))
        db.commit()
    link_directly("telegram", "10", "10", "ivan")
    link_directly("max", "8", "800", "olga")
    occ = new_occurrence(due=TODAY + timedelta(days=1))

    shared = FakeNotifier()
    assert run(shared) == 1
    assert run(shared) == 0
    assert len(shared.messages) == 1 and len(dm.sent) == 2
    tg_call = next(c for c in dm.sent if c[0][0] == "sendMessage")
    assert tg_call[0][1]["chat_id"] == "10" and tg_call[0][1]["reply_markup"]["inline_keyboard"][0][0]["callback_data"] == f"paid:{occ}"
    max_call = next(c for c in dm.sent if c[0][0] == "POST")
    assert max_call[1]["query"]["chat_id"] == 800
    assert deliveries() == sorted(["telegram", f"max:u{user_id('olga')}", f"telegram:u{user_id('ivan')}"])
    assert state(occ)[0] == "unpaid"


def test_blocked_bot_is_not_retried_forever(dm):
    link_directly()
    new_occurrence(due=TODAY + timedelta(days=1))
    dm.fail = "Telegram отклонил запрос sendMessage: Forbidden: bot was blocked by the user (код 403)"
    run()
    dm.fail = None
    run()
    assert dm.sent == []  # после блокировки больше не пытаемся
    with SessionLocal() as db:
        from app.models import PaymentOccurrence

        assert db.scalar(select(PaymentOccurrence.reminded_at)) is not None


def test_temporary_dm_failure_is_retried_without_repeating_the_group(dm):
    link_directly()
    new_occurrence(due=TODAY + timedelta(days=1))
    shared = FakeNotifier()
    dm.fail = "сеть недоступна (ConnectError)"
    run(shared)
    dm.fail = None
    run(shared)
    assert len(dm.sent) == 1 and len(shared.messages) == 1


def test_no_links_means_no_personal_channels(dm):
    new_occurrence(due=TODAY + timedelta(days=1))
    run()
    assert dm.sent == [] and deliveries() == ["telegram"]


def test_personal_channel_needs_bot_token(dm):
    link_directly()
    new_occurrence(due=TODAY + timedelta(days=1))
    with SessionLocal() as db:
        send_due_reminders(db, [FakeNotifier()], Settings(telegram_bot_token=""), TODAY)
    assert dm.sent == []
