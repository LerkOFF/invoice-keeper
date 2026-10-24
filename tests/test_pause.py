from datetime import date, timedelta

from app.api.deps import current_date
from tests.helpers import B, TODAY


def create(admin, first_due="2026-09-05", **extra):
    body = {"name": "Аренда", "amount": "100", "currency": "RUB", "first_due_date": first_due, **extra}
    response = admin.post(f"{B}/recurring-payments", json=body)
    assert response.status_code == 201, response.text
    return response.json()


def dues(client, **params):
    return [(o["due_date"], o["status"]) for o in client.get(f"{B}/payment-occurrences", params=params).json()]


def test_pause_drops_future_unpaid_and_keeps_debts(admin):
    payment = create(admin)  # 5 сен (долг), 5 окт (долг), 5 ноя (будущий)
    response = admin.post(f"{B}/recurring-payments/{payment['id']}/pause", json={})
    assert response.status_code == 200, response.text
    out = response.json()
    assert out["is_paused"] is True and out["paused_from"] == TODAY.isoformat() and out["paused_until"] is None
    # прошлые долги остались, будущий срок в паузе убран
    assert dues(admin) == [("2026-09-05", "unpaid"), ("2026-10-05", "unpaid")]
    entry = admin.get(f"{B}/audit-log", params={"action": "payment.pause"}).json()[0]
    assert entry["details"] == {"name": "Аренда", "until": None}


def test_paused_payment_is_not_planned_or_reminded(app, admin):
    payment = create(admin, first_due="2026-10-25")
    admin.post(f"{B}/recurring-payments/{payment['id']}/pause", json={"until": "2027-01-01"})
    assert dues(admin) == []
    calendar = admin.get(f"{B}/payments/calendar", params={"year": 2026, "month": 11}).json()
    assert calendar["days"] == []
    budget = admin.get(f"{B}/payments/budget", params={"year": 2027, "month": 1}).json()
    rub = next(c for c in budget["currencies"] if c["currency"] == "RUB")
    assert rub["planned"] == "100.00"  # 25 января уже после паузы


def test_resume_skips_paused_months_without_overdue(app, admin):
    payment = create(admin, first_due="2026-10-25")
    admin.post(f"{B}/recurring-payments/{payment['id']}/pause", json={})
    # прошло два месяца: возобновляем 24 декабря
    later = TODAY + timedelta(days=62)
    app.dependency_overrides[current_date] = lambda: later
    resumed = admin.post(f"{B}/recurring-payments/{payment['id']}/resume")
    assert resumed.status_code == 200 and resumed.json()["is_paused"] is False
    # 25 окт и 25 ноя пришлись на паузу и не стали просрочкой; 25 дек уже после паузы
    assert [d for d, _ in dues(admin)] == ["2026-12-25"]
    assert admin.post(f"{B}/recurring-payments/{payment['id']}/resume").status_code == 422


def test_pause_rules_and_rights(admin, user):
    payment = create(admin)
    url = f"{B}/recurring-payments/{payment['id']}"
    assert admin.post(f"{url}/pause", json={"until": TODAY.isoformat()}).status_code == 422
    assert user.post(f"{url}/pause", json={}).status_code == 403
    # повторная пауза меняет дату окончания действующей
    admin.post(f"{url}/pause", json={})
    extended = admin.post(f"{url}/pause", json={"until": "2026-12-01"}).json()
    assert extended["paused_until"] == "2026-12-01" and extended["paused_from"] == TODAY.isoformat()
    listed = [p for p in admin.get(f"{B}/recurring-payments").json() if p["id"] == payment["id"]][0]
    assert listed["is_paused"] is True


def test_reminders_skip_paused(db):
    from decimal import Decimal

    from app.core.config import Settings
    from app.models import PaymentPause, RecurringPayment
    from app.services.periods import ensure_occurrences
    from app.services.reminders import send_due_reminders
    from tests.fakes import FakeNotifier

    payment = RecurringPayment(name="Сервер", currency="USD", first_due_date=TODAY + timedelta(days=2))
    payment.amount = Decimal("20")
    db.add(payment)
    db.flush()
    ensure_occurrences(db, payment, TODAY)
    # пауза, поставленная в обход API (например, в старой базе), напоминание тоже глушит
    payment.pauses.append(PaymentPause(paused_from=TODAY, paused_until=date(2027, 1, 1)))
    db.commit()
    notifier = FakeNotifier()
    assert send_due_reminders(db, notifier, Settings(reminder_days=3), TODAY, personal=False) == 0
    assert notifier.reminders == []
