import json
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import delete, select

from app.core.db import SessionLocal
from app.models import AuditEntry, PaymentOccurrence
from app.services.reminders import send_due_reminders
from app.core.config import Settings
from tests.fakes import FakeNotifier
from tests.helpers import ADMIN, B, TODAY, USER


def log(client, **params):
    response = client.get(f"{B}/audit-log", params=params)
    assert response.status_code == 200, response.text
    return response.json()


def actions(client, **params):
    return [e["action"] for e in log(client, **params)]


def new_payment(admin, due="2026-10-25", name="Аренда"):
    response = admin.post(
        f"{B}/recurring-payments",
        json={"name": name, "amount": "100.00", "currency": "RUB", "first_due_date": due},
    )
    assert response.status_code == 201, response.text
    return response.json()


def first_occurrence(admin) -> int:
    return admin.get(f"{B}/payment-occurrences").json()[0]["id"]


def test_audit_log_is_admin_only(admin, user, anon):
    assert anon.get(f"{B}/audit-log").status_code == 401
    assert user.get(f"{B}/audit-log").status_code == 403
    assert admin.get(f"{B}/audit-log").status_code == 200


def test_no_api_can_modify_or_delete_entries(admin):
    spec = admin.get(f"{B}/openapi.json").json()["paths"]
    assert set(spec["/api/v1/audit-log"]) == {"get"}


def test_login_logout_and_failed_login_are_recorded(app, anon):
    anon.post(f"{B}/auth/login", json={"login": "ivan", "password": "wrong-password-xyz"})
    anon.post(f"{B}/auth/login", json={"login": "nobody", "password": "secret-password-qwe"})
    token = anon.post(f"{B}/auth/login", json=USER).json()["token"]
    anon.post(f"{B}/auth/logout", headers={"Authorization": f"Bearer {token}"})

    from tests.conftest import logged_in

    admin = logged_in(app, ADMIN)
    entries = log(admin, action="auth.")
    admin.__exit__(None, None, None)

    by_action = {}
    for e in entries:
        by_action.setdefault(e["action"], []).append(e)
    assert {e["actor"] for e in by_action["auth.login_failed"]} == {"ivan", "nobody"}
    assert all(e["actor_type"] == "anonymous" for e in by_action["auth.login_failed"])
    assert by_action["auth.login"][0]["actor_type"] in {"user", "admin"}
    assert "auth.logout" in by_action
    assert all(e["ip"] for e in entries)
    # пароли не попадают в журнал ни в каком виде
    dump = json.dumps(entries, ensure_ascii=False)
    assert "wrong-password-xyz" not in dump and "secret-password-qwe" not in dump and USER["password"] not in dump


def test_payment_create_and_delete_are_recorded(admin):
    payment = new_payment(admin)
    admin.delete(f"{B}/recurring-payments/{payment['id']}")

    entries = log(admin, action="payment.")
    assert [e["action"] for e in entries] == ["payment.delete", "payment.create"]  # новые первыми
    created = entries[1]
    assert created["actor"] == "boss" and created["actor_type"] == "admin"
    assert created["target_id"] == payment["id"]
    assert created["details"]["name"] == "Аренда" and created["details"]["amount"] == "100.00"


def test_occurrence_changes_are_recorded_with_actor_and_dates(admin, user):
    new_payment(admin, due="2026-10-20")
    occ = first_occurrence(admin)

    user.patch(f"{B}/payment-occurrences/{occ}", json={"status": "paid"})
    user.patch(f"{B}/payment-occurrences/{occ}", json={"paid_at": "2026-10-19"})
    user.patch(f"{B}/payment-occurrences/{occ}", json={"paid_at": "2026-10-19"})  # без изменений: записи нет
    user.patch(f"{B}/payment-occurrences/{occ}", json={"status": "unpaid"})

    entries = log(admin, action="occurrence.")
    assert [e["action"] for e in entries] == ["occurrence.unpaid", "occurrence.paid_at_changed", "occurrence.paid"]
    paid = entries[2]
    assert paid["actor"] == "ivan" and paid["actor_type"] == "user" and paid["target_id"] == occ
    assert paid["details"]["paid_at"] == TODAY.isoformat() and paid["details"]["source"] == "web"
    changed = entries[1]
    assert changed["details"]["paid_at_before"] == TODAY.isoformat() and changed["details"]["paid_at"] == "2026-10-19"


def test_rejected_changes_leave_no_trace(admin, user):
    new_payment(admin)
    occ = first_occurrence(admin)
    assert user.patch(f"{B}/payment-occurrences/{occ}", json={}).status_code == 422
    assert actions(admin, action="occurrence.") == []


def test_user_management_is_recorded_without_passwords(admin):
    created = admin.post(f"{B}/users", json={"login": "petr", "password": "petr-secret-pass"}).json()
    admin.patch(f"{B}/users/{created['id']}", json={"login": "petr2", "password": "new-secret-pass"})
    admin.delete(f"{B}/users/{created['id']}")

    entries = log(admin, action="user.")
    assert [e["action"] for e in entries] == ["user.delete", "user.update", "user.create"]
    update = entries[1]
    assert update["details"] == {"login": "petr2", "login_before": "petr", "password_changed": True}
    dump = json.dumps(entries, ensure_ascii=False)
    assert "petr-secret-pass" not in dump and "new-secret-pass" not in dump


def test_failed_user_operation_is_not_recorded(admin):
    admin.post(f"{B}/users", json={"login": "boss", "password": "whatever-123"})  # зарезервирован, 409
    assert actions(admin, action="user.") == []


def test_telegram_payment_is_recorded_as_telegram_actor(admin):
    from tests.test_telegram_bot import FakeBotApi, make_bot, new_occurrence, press

    occ = new_occurrence()
    bot, _ = make_bot(FakeBotApi(members={10: {"status": "member"}}))
    bot.process_update(press(occ, username="ivan_tg"))

    [entry] = log(admin, action="occurrence.paid")
    assert entry["actor_type"] == "telegram" and entry["actor"] == "@ivan_tg"
    assert entry["details"]["source"] == "telegram"


def test_reminders_are_recorded_as_system(admin, db):
    from tests.test_reminders import add_payment

    add_payment(db, TODAY + timedelta(days=1))
    # запись идёт в базу приложения, поэтому прогоняем напоминания через неё же
    with SessionLocal() as app_db:
        from app.models import RecurringPayment
        from app.services.periods import ensure_occurrences
        from decimal import Decimal

        payment = RecurringPayment(name="Сервер", currency="USD", first_due_date=TODAY + timedelta(days=1))
        payment.amount = Decimal("20")
        app_db.add(payment)
        app_db.flush()
        ensure_occurrences(app_db, payment, TODAY)
        app_db.commit()
        send_due_reminders(app_db, FakeNotifier(), Settings(), TODAY)

    [entry] = log(admin, action="reminder.")
    assert entry["actor_type"] == "system" and entry["details"]["name"] == "Сервер"
    assert entry["details"]["channel"] == "telegram"


def test_filters_pagination_and_order(admin, user):
    new_payment(admin)
    occ = first_occurrence(admin)
    user.patch(f"{B}/payment-occurrences/{occ}", json={"status": "paid"})

    everything = log(admin)
    ids = [e["id"] for e in everything]
    assert ids == sorted(ids, reverse=True)

    assert actions(admin, action="payment.create") == ["payment.create"]
    assert set(actions(admin, action="auth.")) <= {"auth.login", "auth.login_failed", "auth.logout"}
    assert {e["actor"] for e in log(admin, actor="ivan")} == {"ivan"}
    assert log(admin, actor="никто") == []

    assert [e["id"] for e in log(admin, limit=1)] == ids[:1]
    assert [e["id"] for e in log(admin, limit=1, offset=1)] == ids[1:2]

    today = datetime.now(UTC).date()
    assert len(log(admin, since=today.isoformat())) == len(everything)
    assert log(admin, since=(today + timedelta(days=1)).isoformat()) == []
    assert len(log(admin, until=today.isoformat())) == len(everything)
    assert log(admin, until=(today - timedelta(days=1)).isoformat()) == []


def test_entries_survive_deleting_their_targets(admin):
    payment = new_payment(admin)
    admin.delete(f"{B}/recurring-payments/{payment['id']}")
    with SessionLocal() as db:
        db.execute(delete(PaymentOccurrence))
        db.commit()
        assert db.scalar(select(AuditEntry.id).where(AuditEntry.action == "payment.create")) is not None
