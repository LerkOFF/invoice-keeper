from datetime import date  # noqa: F401

import pytest

from tests.helpers import ADMIN, B, TODAY, USER  # noqa: F401


def create_payment(admin, name="Аренда", amount="100.50", currency="RUB", first_due="2026-10-25"):
    response = admin.post(
        f"{B}/recurring-payments",
        json={"name": name, "amount": amount, "currency": currency, "first_due_date": first_due},
    )
    assert response.status_code == 201, response.text
    return response.json()


def occurrences(client, **params):
    response = client.get(f"{B}/payment-occurrences", params=params)
    assert response.status_code == 200, response.text
    return response.json()


# ---------- регулярные платежи ----------


def test_only_admin_creates_payments(admin, user, anon):
    body = {"name": "x", "amount": "1.00", "currency": "USD", "first_due_date": "2026-11-01"}
    assert anon.post(f"{B}/recurring-payments", json=body).status_code == 401
    assert user.post(f"{B}/recurring-payments", json=body).status_code == 403
    assert admin.post(f"{B}/recurring-payments", json=body).status_code == 201


@pytest.mark.parametrize(
    "patch",
    [
        {"amount": "0"},
        {"amount": "-5"},
        {"amount": "10.555"},
        {"amount": "abc"},
        {"currency": "GBP"},
        {"name": ""},
        {"first_due_date": "not-a-date"},
        {"period": "weekly"},
    ],
)
def test_create_validation(admin, patch):
    body = {"name": "x", "amount": "1.00", "currency": "USD", "first_due_date": "2026-11-01", **patch}
    assert admin.post(f"{B}/recurring-payments", json=body).status_code == 422


def test_create_returns_payment_and_generates_first_period(admin):
    payment = create_payment(admin, amount="45000", currency="RUB")
    assert payment["amount"] == "45000.00"
    assert payment["currency"] == "RUB" and payment["period"] == "monthly"

    items = occurrences(admin)
    assert [(i["due_date"], i["status"]) for i in items] == [("2026-10-25", "unpaid")]


def test_create_in_the_past_generates_all_periods_up_to_horizon(admin):
    create_payment(admin, first_due="2026-08-05")
    assert [i["due_date"] for i in occurrences(admin)] == [
        "2026-08-05",
        "2026-09-05",
        "2026-10-05",
        "2026-11-05",
    ]


def test_create_yearly_payment_via_api(admin):
    body = {"name": "Домен", "amount": "1290", "currency": "RUB", "first_due_date": "2026-03-01", "period": "yearly"}
    response = admin.post(f"{B}/recurring-payments", json=body)
    assert response.status_code == 201, response.text
    assert response.json()["period"] == "yearly"
    # прошлый годовой срок просрочен, следующий через год уже виден
    assert [(i["due_date"], i["is_overdue"]) for i in occurrences(admin)] == [
        ("2026-03-01", True),
        ("2027-03-01", False),
    ]


def test_list_payments_available_to_user(admin, user):
    create_payment(admin, name="Сервер", currency="USD")
    names = [p["name"] for p in user.get(f"{B}/recurring-payments").json()]
    assert names == ["Сервер"]


def test_delete_is_admin_only_and_soft(admin, user, anon):
    payment_id = create_payment(admin)["id"]

    assert anon.delete(f"{B}/recurring-payments/{payment_id}").status_code == 401
    assert user.delete(f"{B}/recurring-payments/{payment_id}").status_code == 403
    assert admin.delete(f"{B}/recurring-payments/{payment_id}").status_code == 204

    assert admin.get(f"{B}/recurring-payments").json() == []
    assert len(admin.get(f"{B}/recurring-payments", params={"include_deleted": True}).json()) == 1
    # история сохранена
    assert occurrences(admin) == []
    history = occurrences(admin, include_deleted=True)
    assert len(history) == 1 and history[0]["payment_deleted"] is True


def test_delete_unknown_or_twice_gives_404(admin):
    assert admin.delete(f"{B}/recurring-payments/999").status_code == 404
    payment_id = create_payment(admin)["id"]
    admin.delete(f"{B}/recurring-payments/{payment_id}")
    assert admin.delete(f"{B}/recurring-payments/{payment_id}").status_code == 404


def test_everything_requires_auth(anon):
    for method, path in [
        ("get", "/recurring-payments"),
        ("get", "/payment-occurrences"),
        ("get", "/payment-occurrences/1"),
        ("patch", "/payment-occurrences/1"),
        ("get", "/payments/summary"),
    ]:
        assert getattr(anon, method)(f"{B}{path}").status_code == 401, path


# ---------- просрочка ----------


def make_payment_with_due(admin, due: str, name="P", amount="10.00", currency="RUB") -> int:
    create_payment(admin, name=name, amount=amount, currency=currency, first_due=due)
    return occurrences(admin, recurring_id=admin.get(f"{B}/recurring-payments").json()[-1]["id"])[0]["id"]


def test_overdue_starts_next_day_after_due(admin):
    yesterday = make_payment_with_due(admin, "2026-10-22", name="Вчера")
    today = make_payment_with_due(admin, "2026-10-23", name="Сегодня")
    tomorrow = make_payment_with_due(admin, "2026-10-24", name="Завтра")

    get = lambda i: admin.get(f"{B}/payment-occurrences/{i}").json()
    assert (get(yesterday)["is_overdue"], get(yesterday)["overdue_days"]) == (True, 1)
    assert (get(today)["is_overdue"], get(today)["overdue_days"]) == (False, 0)
    assert (get(tomorrow)["is_overdue"], get(tomorrow)["overdue_days"]) == (False, 0)


def test_paid_on_due_day_is_on_time_and_later_is_overdue(admin):
    occ = make_payment_with_due(admin, "2026-10-20")

    on_time = admin.patch(f"{B}/payment-occurrences/{occ}", json={"status": "paid", "paid_at": "2026-10-20"}).json()
    assert on_time["is_overdue"] is False

    late = admin.patch(f"{B}/payment-occurrences/{occ}", json={"paid_at": "2026-10-21"}).json()
    assert late["is_overdue"] is True and late["overdue_days"] == 1
    assert late["due_date"] == "2026-10-20"  # срок не менялся


def test_correcting_paid_date_removes_false_overdue(admin, user):
    occ = make_payment_with_due(admin, "2026-10-10")
    # отметили сегодня: оплата с опозданием
    marked = user.patch(f"{B}/payment-occurrences/{occ}", json={"status": "paid"}).json()
    assert marked["paid_at"] == "2026-10-23" and marked["is_overdue"] is True

    fixed = user.patch(f"{B}/payment-occurrences/{occ}", json={"paid_at": "2026-10-09"}).json()
    assert fixed["is_overdue"] is False and fixed["overdue_days"] == 0
    assert fixed["due_date"] == "2026-10-10"
    assert occurrences(admin, overdue=True) == []


# ---------- PATCH оплаты ----------


def test_user_marks_and_cancels_payment(user, admin):
    occ = make_payment_with_due(admin, "2026-10-25")

    paid = user.patch(f"{B}/payment-occurrences/{occ}", json={"status": "paid"}).json()
    assert paid["status"] == "paid" and paid["paid_at"] == "2026-10-23"

    cancelled = user.patch(f"{B}/payment-occurrences/{occ}", json={"status": "unpaid"}).json()
    assert cancelled["status"] == "unpaid" and cancelled["paid_at"] is None


def test_mark_with_explicit_date_and_keep_existing_date(user, admin):
    occ = make_payment_with_due(admin, "2026-10-25")
    user.patch(f"{B}/payment-occurrences/{occ}", json={"status": "paid", "paid_at": "2026-10-20"})
    again = user.patch(f"{B}/payment-occurrences/{occ}", json={"status": "paid"}).json()
    assert again["paid_at"] == "2026-10-20"


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"status": "paid", "paid_at": "2026-10-24"},  # будущее
        {"status": "unpaid", "paid_at": "2026-10-01"},
        {"paid_at": "2026-10-01"},  # период ещё не оплачен
        {"status": "bogus"},
        {"amount": "5.00"},  # чужие поля запрещены
        {"status": "paid", "due_date": "2026-01-01"},
    ],
)
def test_patch_rejects_invalid_requests(user, admin, body):
    occ = make_payment_with_due(admin, "2026-10-25")
    assert user.patch(f"{B}/payment-occurrences/{occ}", json=body).status_code == 422


def test_cannot_clear_date_of_paid_period(user, admin):
    occ = make_payment_with_due(admin, "2026-10-25")
    user.patch(f"{B}/payment-occurrences/{occ}", json={"status": "paid"})
    assert user.patch(f"{B}/payment-occurrences/{occ}", json={"paid_at": None}).status_code == 422


def test_patch_unknown_and_anonymous(admin, anon):
    assert admin.patch(f"{B}/payment-occurrences/999", json={"status": "paid"}).status_code == 404
    assert anon.patch(f"{B}/payment-occurrences/1", json={"status": "paid"}).status_code == 401


def test_patch_of_deleted_payment_is_conflict(admin):
    occ = make_payment_with_due(admin, "2026-10-25")
    payment_id = admin.get(f"{B}/recurring-payments").json()[0]["id"]
    admin.delete(f"{B}/recurring-payments/{payment_id}")
    assert admin.patch(f"{B}/payment-occurrences/{occ}", json={"status": "paid"}).status_code == 409


def test_marking_one_period_keeps_other_periods_untouched(admin, user):
    create_payment(admin, first_due="2026-09-05")  # 5 сен, 5 окт, 5 ноя
    first, second, third = occurrences(admin)
    user.patch(f"{B}/payment-occurrences/{first['id']}", json={"status": "paid", "paid_at": "2026-09-05"})

    after = occurrences(admin)
    assert [i["status"] for i in after] == ["paid", "unpaid", "unpaid"]
    assert after[1]["is_overdue"] is True  # просрочка не останавливает следующие периоды
    assert after[2]["is_overdue"] is False and after[2]["status"] == "unpaid"  # отдельный статус


# ---------- фильтры ----------


def test_filters(admin, user):
    paid = make_payment_with_due(admin, "2026-10-01", name="A", currency="RUB")
    make_payment_with_due(admin, "2026-10-10", name="B", currency="USD")  # просрочен
    make_payment_with_due(admin, "2026-10-28", name="C", currency="EUR")
    user.patch(f"{B}/payment-occurrences/{paid}", json={"status": "paid", "paid_at": "2026-10-01"})

    # платежи с прошлым сроком уже дали и ноябрьские периоды, смотрим только октябрь
    names = lambda **p: sorted(i["name"] for i in occurrences(admin, **{"due_to": "2026-10-31", **p}))
    assert names(status="paid") == ["A"]
    assert names(status="unpaid") == ["B", "C"]
    assert names(overdue="true") == ["B"]
    assert names(overdue="false") == ["A", "C"]
    assert names(currency="EUR") == ["C"]
    assert names(due_from="2026-10-05", due_to="2026-10-15") == ["B"]
    assert names(due_to="2026-11-30", currency="USD") == ["B", "B"]


def test_pagination(admin):
    create_payment(admin, first_due="2026-06-05")
    all_items = occurrences(admin)
    assert len(all_items) == 6
    assert [i["id"] for i in occurrences(admin, limit=2, offset=1)] == [i["id"] for i in all_items[1:3]]


# ---------- summary ----------


def test_summary_by_currency_without_conversion(admin, user):
    paid = make_payment_with_due(admin, "2026-10-01", amount="100.00", currency="RUB")
    make_payment_with_due(admin, "2026-10-10", amount="20.00", currency="USD")  # просрочен
    make_payment_with_due(admin, "2026-10-28", amount="9.99", currency="EUR")
    make_payment_with_due(admin, "2026-10-12", amount="50.50", currency="RUB")  # просрочен
    user.patch(f"{B}/payment-occurrences/{paid}", json={"status": "paid", "paid_at": "2026-10-01"})

    body = user.get(f"{B}/payments/summary", params={"due_to": "2026-10-31"}).json()
    assert body["as_of"] == "2026-10-23"
    by = {c["currency"]: c for c in body["currencies"]}
    assert list(by) == ["RUB", "USD", "EUR"]

    assert (by["RUB"]["total"], by["RUB"]["paid"], by["RUB"]["unpaid"], by["RUB"]["overdue"]) == (
        "150.50",
        "100.00",
        "50.50",
        "50.50",
    )
    assert (by["USD"]["total"], by["USD"]["overdue"], by["USD"]["count_overdue"]) == ("20.00", "20.00", 1)
    assert (by["EUR"]["total"], by["EUR"]["overdue"], by["EUR"]["count_unpaid"]) == ("9.99", "0.00", 1)


def test_summary_has_all_currencies_when_empty_and_hides_deleted(admin):
    body = admin.get(f"{B}/payments/summary").json()
    assert [c["currency"] for c in body["currencies"]] == ["RUB", "USD", "EUR"]
    assert all(c["total"] == "0.00" and c["count_total"] == 0 for c in body["currencies"])

    payment = create_payment(admin, amount="10.00", currency="USD")
    admin.delete(f"{B}/recurring-payments/{payment['id']}")
    usd = [c for c in admin.get(f"{B}/payments/summary").json()["currencies"] if c["currency"] == "USD"][0]
    assert usd["total"] == "0.00"
    usd = [
        c
        for c in admin.get(f"{B}/payments/summary", params={"include_deleted": True}).json()["currencies"]
        if c["currency"] == "USD"
    ][0]
    assert usd["total"] == "10.00"
