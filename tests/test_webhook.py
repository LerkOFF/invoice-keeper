import json
import logging
from datetime import timedelta

import httpx
import pytest

from app.core.config import Settings
from app.core.db import SessionLocal
from app.models import RecurringPayment
from app.services import webhook
from app.services.notify import NotifyError, Reminder
from app.services.webhook import WebhookNotifier, matches, sign
from app.services.telegram import build_notifiers
from tests.helpers import B, TODAY

URL = "https://hooks.example.com/services/T000/SECRET-PATH"


def reminder(**over):
    base = dict(
        occurrence_id=7,
        payment_id=3,
        name="Аренда",
        amount="45000.00",
        currency="RUB",
        due_date=TODAY + timedelta(days=2),
        days_left=2,
        text="🔔 Напоминание об оплате\n\nПлатёж: Аренда",
    )
    from decimal import Decimal

    base["amount"] = Decimal(base["amount"])
    return Reminder(**(base | over))


def make(handler, **settings) -> WebhookNotifier:
    return WebhookNotifier(Settings(webhook_url=URL, **settings), transport=httpx.MockTransport(handler))


# ---------- канал напоминаний ----------


def test_reminder_is_posted_as_json_with_chat_compatible_fields():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        seen["headers"] = request.headers
        return httpx.Response(200)

    make(handler).send(reminder())

    body = seen["body"]
    assert seen["url"] == URL and body["event"] == "reminder.due"
    assert body["text"] == body["content"] == "🔔 Напоминание об оплате\n\nПлатёж: Аренда"  # Slack/Mattermost и Discord
    assert body["data"] == {
        "occurrence_id": 7,
        "payment_id": 3,
        "name": "Аренда",
        "amount": "45000.00",
        "currency": "RUB",
        "due_date": (TODAY + timedelta(days=2)).isoformat(),
        "days_left": 2,
        "is_overdue": False,
    }
    assert body["sent_at"].endswith("Z")
    assert seen["headers"]["x-invoice-keeper-event"] == "reminder.due" and seen["headers"]["x-invoice-keeper-delivery"]
    assert "x-invoice-keeper-signature" not in seen["headers"]


def test_signature_lets_the_receiver_verify_the_body():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["raw"] = request.content
        seen["sig"] = request.headers["x-invoice-keeper-signature"]
        return httpx.Response(204)

    make(handler, webhook_secret="s3cret").send(reminder())

    assert seen["sig"] == sign("s3cret", seen["raw"]) and seen["sig"].startswith("sha256=")
    assert seen["sig"] != sign("other", seen["raw"])  # другой секрет даёт другую подпись


@pytest.mark.parametrize("code", [301, 400, 404, 500, 503])
def test_non_2xx_is_an_error(code):
    with pytest.raises(NotifyError, match=str(code)):
        make(lambda _: httpx.Response(code)).send(reminder())


def test_network_failure_does_not_leak_secret_url():
    def handler(request):
        raise httpx.ConnectError(f"cannot connect to {request.url}")

    with pytest.raises(NotifyError) as error:
        make(handler).send(reminder())
    assert "SECRET-PATH" not in str(error.value) and "ConnectError" in str(error.value)


def test_configured_only_for_http_urls():
    assert WebhookNotifier(Settings(webhook_url=URL)).configured
    assert WebhookNotifier(Settings(webhook_url="http://localhost:9000/hook")).configured
    for bad in ("", "   ", "ftp://x.example/h", "javascript:alert(1)", "hooks.example.com/x"):
        assert not WebhookNotifier(Settings(webhook_url=bad)).configured
    with pytest.raises(NotifyError):
        WebhookNotifier(Settings(webhook_url="")).send(reminder())


def test_notifiers_list_contains_webhook_only_configured_when_url_set():
    by_name = {n.name: n for n in build_notifiers(Settings(webhook_url=URL))}
    assert set(by_name) == {"telegram", "webhook"} and by_name["webhook"].configured
    assert not {n.name: n for n in build_notifiers(Settings())}["webhook"].configured


# ---------- события журнала ----------


class SyncExecutor:
    def submit(self, fn, *args):
        fn(*args)


@pytest.fixture
def hook(monkeypatch):
    """Подменяет получателя: события собираются в список, а не уходят в сеть."""
    delivered: list[dict] = []
    monkeypatch.setattr(webhook, "_executor", SyncExecutor())
    monkeypatch.setattr(webhook, "get_settings", lambda: Settings(webhook_url=URL))
    monkeypatch.setattr(webhook, "_deliver", lambda _settings, payload: delivered.append(payload))
    return delivered


def create_payment(admin):
    return admin.post(
        f"{B}/recurring-payments",
        json={"name": "Аренда", "amount": "100.00", "currency": "RUB", "first_due_date": "2026-10-25"},
    )


def test_matches_exact_names_and_groups():
    filters = ["payment.", "occurrence.paid"]
    assert matches(filters, "payment.create") and matches(filters, "occurrence.paid")
    assert not matches(filters, "occurrence.unpaid") and not matches(filters, "auth.login")
    assert not matches([], "payment.create")


def test_default_events_cover_changes_but_not_logins_or_reminders(admin, user, hook):
    create_payment(admin)
    occ = admin.get(f"{B}/payment-occurrences").json()[0]["id"]
    user.patch(f"{B}/payment-occurrences/{occ}", json={"status": "paid"})

    names = [e["event"] for e in hook]
    assert names == ["payment.create", "occurrence.paid"]  # входы (auth.) в список по умолчанию не входят


def test_event_payload_describes_actor_target_and_details(admin, user, hook):
    create_payment(admin)
    occ = admin.get(f"{B}/payment-occurrences").json()[0]["id"]
    user.patch(f"{B}/payment-occurrences/{occ}", json={"status": "paid"})

    paid = hook[1]
    assert paid["text"] == "Оплата отмечена: Аренда"
    assert paid["actor"] == {"type": "user", "name": "ivan"}
    assert paid["target"] == {"type": "occurrence", "id": occ}
    assert paid["details"]["name"] == "Аренда" and paid["details"]["source"] == "web"
    assert paid["at"].endswith("Z")


def test_rejected_action_sends_no_event(admin, user, hook):
    create_payment(admin)
    hook.clear()
    assert user.patch(f"{B}/payment-occurrences/1", json={}).status_code == 422
    assert user.post(f"{B}/recurring-payments", json={}).status_code in {403, 422}
    assert hook == []


def test_events_are_sent_only_after_commit_and_dropped_on_rollback(hook):
    from app.services import audit

    with SessionLocal() as db:
        audit.record(db, "payment.create", audit.Actor("admin", "boss"), "payment", 1, {"name": "X"})
        assert hook == []  # до коммита ничего не уходит
        db.rollback()
    assert hook == []

    with SessionLocal() as db:
        audit.record(db, "payment.create", audit.Actor("admin", "boss"), "payment", 2, {"name": "Y"})
        db.commit()
    assert [e["target"]["id"] for e in hook] == [2]


def test_custom_event_filter_and_user_events_without_passwords(admin, monkeypatch):
    delivered = []
    monkeypatch.setattr(webhook, "_executor", SyncExecutor())
    monkeypatch.setattr(webhook, "get_settings", lambda: Settings(webhook_url=URL, webhook_events="user.,auth.login"))
    monkeypatch.setattr(webhook, "_deliver", lambda _s, payload: delivered.append(payload))

    created = admin.post(f"{B}/users", json={"login": "petr", "password": "petr-secret-pass"}).json()
    admin.patch(f"{B}/users/{created['id']}", json={"password": "new-secret-pass"})
    create_payment(admin)  # payment. в фильтр не входит

    assert [e["event"] for e in delivered] == ["user.create", "user.update"]
    assert "secret-pass" not in json.dumps(delivered)
    assert delivered[1]["details"]["password_changed"] is True


def test_no_url_means_no_events(admin, monkeypatch):
    called = []
    monkeypatch.setattr(webhook, "get_settings", lambda: Settings(webhook_url=""))
    monkeypatch.setattr(webhook, "_deliver", lambda *a: called.append(a))
    create_payment(admin)
    assert called == []


# ---------- повторные попытки ----------


def test_event_delivery_retries_then_succeeds(monkeypatch):
    monkeypatch.setattr(webhook.time, "sleep", lambda _s: None)
    attempts = []

    def handler(request: httpx.Request) -> httpx.Response:
        attempts.append(json.loads(request.content)["event"])
        return httpx.Response(503 if len(attempts) < 3 else 200)

    payload = {"event": "payment.create", "text": "Платёж добавлен: Аренда", "at": "2026-10-23T10:00:00Z", "details": {}}
    webhook._deliver(Settings(webhook_url=URL), payload, httpx.MockTransport(handler))
    assert attempts == ["payment.create"] * 3


def test_event_delivery_gives_up_after_three_attempts_and_logs(monkeypatch, caplog):
    monkeypatch.setattr(webhook.time, "sleep", lambda _s: None)
    attempts = []

    def handler(_request):
        attempts.append(1)
        return httpx.Response(500)

    payload = {"event": "payment.create", "text": "x", "details": {}}
    with caplog.at_level(logging.ERROR, logger="invoice_keeper"):
        webhook._deliver(Settings(webhook_url=URL), payload, httpx.MockTransport(handler))
    assert len(attempts) == 3
    assert "не доставлен" in caplog.text and "SECRET-PATH" not in caplog.text
