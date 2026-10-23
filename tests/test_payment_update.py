from sqlalchemy import create_engine, inspect, text

from app.core.db import migrate
from tests.helpers import B


def create(admin, **extra):
    body = {"name": "Аренда", "amount": "100.00", "currency": "RUB", "first_due_date": "2026-08-05", **extra}
    response = admin.post(f"{B}/recurring-payments", json=body)
    assert response.status_code == 201, response.text
    return response.json()


def periods(client, **params):
    return client.get(f"{B}/payment-occurrences", params=params).json()


def pay(client, occurrence_id, paid_at):
    response = client.patch(f"{B}/payment-occurrences/{occurrence_id}", json={"status": "paid", "paid_at": paid_at})
    assert response.status_code == 200, response.text


def test_new_amount_applies_only_to_unpaid_periods_from_today(admin):
    payment = create(admin)
    by_due = {o["due_date"]: o for o in periods(admin)}
    pay(admin, by_due["2026-08-05"]["id"], "2026-08-05")

    response = admin.patch(f"{B}/recurring-payments/{payment['id']}", json={"amount": "150"})
    assert response.status_code == 200, response.text
    assert response.json()["amount"] == "150.00"

    amounts = {o["due_date"]: o["amount"] for o in periods(admin)}
    # оплаченный и просроченный периоды сохраняют свою сумму, впереди новая
    assert amounts == {
        "2026-08-05": "100.00",
        "2026-09-05": "100.00",
        "2026-10-05": "100.00",
        "2026-11-05": "150.00",
    }
    rub = next(c for c in admin.get(f"{B}/payments/summary").json()["currencies"] if c["currency"] == "RUB")
    assert rub["total"] == "450.00" and rub["paid"] == "100.00" and rub["overdue"] == "200.00"

    # будущие месяцы бюджета считаются по новой сумме, прошлые по своей
    months = {m["month"]: m for m in admin.get(f"{B}/payments/budget", params={"year": 2026}).json()["months"]}
    planned = lambda m: next(line["planned"] for line in months[m]["currencies"] if line["currency"] == "RUB")  # noqa: E731
    assert planned(9) == "100.00" and planned(12) == "150.00"


def test_rename_keeps_history_and_is_logged(admin):
    payment = create(admin)
    response = admin.patch(f"{B}/recurring-payments/{payment['id']}", json={"name": "Аренда склада"})
    assert response.status_code == 200
    assert {o["name"] for o in periods(admin)} == {"Аренда склада"}
    entry = admin.get(f"{B}/audit-log", params={"action": "payment.update"}).json()[0]
    assert entry["details"]["name_before"] == "Аренда" and entry["details"]["name"] == "Аренда склада"


def test_new_schedule_drops_unpaid_future_periods_and_keeps_history(admin):
    payment = create(admin)
    by_due = {o["due_date"]: o for o in periods(admin)}
    pay(admin, by_due["2026-08-05"]["id"], "2026-08-05")

    response = admin.patch(
        f"{B}/recurring-payments/{payment['id']}", json={"period": "quarterly", "first_due_date": "2026-12-20"}
    )
    assert response.status_code == 200, response.text
    assert response.json()["period"] == "quarterly" and response.json()["first_due_date"] == "2026-12-20"

    # прошлые периоды на месте (оплаченный и два просроченных), 5 ноября старого графика убран, 20 декабря создан
    assert [(o["due_date"], o["status"]) for o in periods(admin)] == [
        ("2026-08-05", "paid"),
        ("2026-09-05", "unpaid"),
        ("2026-10-05", "unpaid"),
        ("2026-12-20", "unpaid"),
    ]
    # прошлые периоды старого графика видны и в календаре
    september = admin.get(f"{B}/payments/calendar", params={"year": 2026, "month": 9}).json()
    assert [d["day"] for d in september["days"]] == ["2026-09-05"]


def test_paid_in_advance_period_survives_schedule_change(admin):
    payment = create(admin)
    by_due = {o["due_date"]: o for o in periods(admin)}
    pay(admin, by_due["2026-11-05"]["id"], "2026-10-20")

    admin.patch(f"{B}/recurring-payments/{payment['id']}", json={"first_due_date": "2026-11-15"})
    dues = [(o["due_date"], o["status"]) for o in periods(admin, due_from="2026-11-01")]
    assert dues == [("2026-11-05", "paid"), ("2026-11-15", "unpaid")]


def test_schedule_change_rules(admin):
    payment = create(admin)
    url = f"{B}/recurring-payments/{payment['id']}"
    assert admin.patch(url, json={"period": "yearly"}).status_code == 422  # нужна дата ближайшей оплаты
    assert admin.patch(url, json={"first_due_date": "2026-10-01"}).status_code == 422  # в прошлом
    assert admin.patch(url, json={"currency": "USD"}).status_code == 422  # валюту не меняем
    assert admin.patch(url, json={}).status_code == 422
    assert admin.patch(url, json={"amount": "0"}).status_code == 422


def test_only_admin_can_edit_and_deleted_payment_is_404(admin, user):
    payment = create(admin)
    url = f"{B}/recurring-payments/{payment['id']}"
    assert user.patch(url, json={"amount": "1"}).status_code == 403
    assert admin.delete(url).status_code == 204
    assert admin.patch(url, json={"amount": "1"}).status_code == 404


def test_migration_adds_amount_column_to_old_database(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path}/old.db")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE recurring_payments (id INTEGER PRIMARY KEY, amount_minor INTEGER)"))
        conn.execute(text("CREATE TABLE payment_occurrences (id INTEGER PRIMARY KEY, recurring_id INTEGER)"))
        conn.execute(text("INSERT INTO recurring_payments VALUES (1, 4500000)"))
        conn.execute(text("INSERT INTO payment_occurrences VALUES (10, 1)"))

    migrate(engine)
    migrate(engine)  # повторный запуск безвреден

    columns = {c["name"] for c in inspect(engine).get_columns("payment_occurrences")}
    assert {"amount_minor", "overdue_reminded_at"} <= columns
    with engine.connect() as conn:
        assert conn.execute(text("SELECT amount_minor FROM payment_occurrences")).scalar() == 4500000
