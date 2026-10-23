from datetime import date

import pytest

from app.services.planning import projected_due_dates
from tests.helpers import B


def create(admin, name, amount, currency, first_due):
    response = admin.post(
        f"{B}/recurring-payments",
        json={"name": name, "amount": amount, "currency": currency, "first_due_date": first_due},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def occurrences(client, **params):
    return client.get(f"{B}/payment-occurrences", params=params).json()


def pay(client, occurrence_id, paid_at):
    response = client.patch(f"{B}/payment-occurrences/{occurrence_id}", json={"status": "paid", "paid_at": paid_at})
    assert response.status_code == 200, response.text


def line(body, currency):
    return next(c for c in body["currencies"] if c["currency"] == currency)


# ---------- расчёт будущих сроков ----------


def test_projection_clamps_to_month_end_and_returns_to_anchor():
    dues = list(projected_due_dates(date(2026, 1, 31), date(2026, 1, 1), date(2026, 5, 31)))
    assert dues == [date(2026, 1, 31), date(2026, 2, 28), date(2026, 3, 31), date(2026, 4, 30), date(2026, 5, 31)]


def test_projection_respects_window_and_first_due():
    assert list(projected_due_dates(date(2026, 8, 5), date(2026, 1, 1), date(2026, 7, 31))) == []
    assert list(projected_due_dates(date(2026, 8, 5), date(2026, 10, 6), date(2026, 12, 31))) == [
        date(2026, 11, 5),
        date(2026, 12, 5),
    ]
    assert list(projected_due_dates(date(2026, 8, 5), date(2026, 12, 6), date(2026, 12, 4))) == []


def test_projection_far_in_the_future_is_cheap_and_correct():
    dues = list(projected_due_dates(date(2020, 3, 15), date(2090, 6, 1), date(2090, 6, 30)))
    assert dues == [date(2090, 6, 15)]


# ---------- итоги на дату ----------


def test_summary_on_a_date_uses_state_at_that_date(admin, user):
    create(admin, "Аренда", "100.00", "RUB", "2026-09-18")
    sep, oct_ = occurrences(admin)[:2]
    pay(user, sep["id"], "2026-10-01")  # сентябрьский период оплачен только 1 октября

    def rub(**params):
        return line(admin.get(f"{B}/payments/summary", params=params).json(), "RUB")

    before_payment = rub(on="2026-09-30")
    assert before_payment["count_total"] == 1 and before_payment["count_paid"] == 0
    assert before_payment["overdue"] == "100.00" and before_payment["count_overdue"] == 1  # 18.09 < 30.09, ещё не оплачен

    after_payment = rub(on="2026-10-01")
    assert after_payment["paid"] == "100.00" and after_payment["overdue"] == "0.00"

    assert rub(on="2026-09-10")["count_total"] == 0  # до первого срока ничего нет
    assert rub(on="2026-10-20")["count_total"] == 2 and rub(on="2026-10-20")["overdue"] == "100.00"  # октябрь не оплачен

    body = admin.get(f"{B}/payments/summary", params={"on": "2026-09-30"}).json()
    assert body["as_of"] == "2026-09-30"


def test_summary_without_on_is_unchanged(admin):
    create(admin, "Аренда", "100.00", "RUB", "2026-09-18")
    body = admin.get(f"{B}/payments/summary").json()
    assert body["as_of"] == "2026-10-23" and line(body, "RUB")["count_total"] == 3  # сен, окт, ноя


# ---------- бюджет ----------


def test_budget_month_future_is_planned_without_periods_in_db(admin):
    create(admin, "Аренда", "45000.00", "RUB", "2026-08-05")
    create(admin, "Сервер", "20.00", "USD", "2026-10-25")
    assert not [o for o in occurrences(admin) if o["due_date"] >= "2027-01-01"]  # в базе будущего нет

    body = admin.get(f"{B}/payments/budget", params={"year": 2027, "month": 3}).json()
    assert body["year"] == 2027 and body["month"] == 3 and body["months"] is None
    rub, usd, eur = (line(body, c) for c in ("RUB", "USD", "EUR"))
    assert (rub["planned"], rub["paid"], rub["remaining"], rub["count_planned"]) == ("45000.00", "0.00", "45000.00", 1)
    assert (usd["planned"], eur["planned"]) == ("20.00", "0.00")  # валюты не смешиваются
    assert [c["currency"] for c in body["currencies"]] == ["RUB", "USD", "EUR"]


def test_budget_year_breaks_down_by_month_and_counts_paid(admin, user):
    create(admin, "Аренда", "45000.00", "RUB", "2026-08-05")
    aug = occurrences(admin)[0]
    pay(user, aug["id"], "2026-08-05")

    body = admin.get(f"{B}/payments/budget", params={"year": 2026}).json()
    assert body["month"] is None and len(body["months"]) == 12
    rub = line(body, "RUB")
    assert (rub["planned"], rub["paid"], rub["remaining"]) == ("225000.00", "45000.00", "180000.00")  # авг-дек, 5 периодов
    assert rub["count_planned"] == 5 and rub["count_paid"] == 1

    by_month = {m["month"]: line(m, "RUB") for m in body["months"]}
    assert all(by_month[m]["planned"] == "0.00" for m in range(1, 8))
    assert by_month[8]["paid"] == "45000.00" and by_month[9]["paid"] == "0.00"
    assert all(by_month[m]["planned"] == "45000.00" for m in range(8, 13))
    assert sum(float(by_month[m]["planned"]) for m in by_month) == float(rub["planned"])


def test_budget_default_year_is_current(admin):
    create(admin, "Сервер", "20.00", "USD", "2026-10-25")
    body = admin.get(f"{B}/payments/budget").json()
    assert body["year"] == 2026 and line(body, "USD")["count_planned"] == 3  # окт, ноя, дек


def test_budget_before_first_due_is_zero(admin):
    create(admin, "Аренда", "100.00", "RUB", "2026-08-05")
    body = admin.get(f"{B}/payments/budget", params={"year": 2026, "month": 7}).json()
    assert line(body, "RUB")["planned"] == "0.00"


def test_budget_hides_deleted_payments_unless_asked(admin):
    payment = create(admin, "Аренда", "100.00", "RUB", "2026-08-05")
    admin.delete(f"{B}/recurring-payments/{payment}")

    assert line(admin.get(f"{B}/payments/budget", params={"year": 2026}).json(), "RUB")["planned"] == "0.00"
    history = admin.get(f"{B}/payments/budget", params={"year": 2026, "include_deleted": True}).json()
    assert line(history, "RUB")["count_planned"] == 4  # только созданные периоды (авг-ноя), будущее не планируется


@pytest.mark.parametrize("params", [{"month": 13}, {"month": 0}, {"year": 1999}, {"year": 2101}, {"month": "x"}])
def test_budget_validation(admin, params):
    assert admin.get(f"{B}/payments/budget", params=params).status_code == 422


def test_budget_and_calendar_require_login(anon):
    assert anon.get(f"{B}/payments/budget").status_code == 401
    assert anon.get(f"{B}/payments/calendar").status_code == 401


def test_budget_available_to_regular_user(admin, user):
    create(admin, "Сервер", "20.00", "USD", "2026-10-25")
    assert user.get(f"{B}/payments/budget").status_code == 200


# ---------- календарь ----------


def test_calendar_current_month_has_real_statuses_by_day(admin, user):
    create(admin, "Аренда", "100.00", "RUB", "2026-10-10")  # просрочена
    create(admin, "Сервер", "20.00", "USD", "2026-10-25")
    create(admin, "Домен", "5.00", "EUR", "2026-10-25")
    rent = occurrences(admin)[0]
    pay(user, occurrences(admin, recurring_id=rent["recurring_id"])[0]["id"], "2026-10-10")

    body = admin.get(f"{B}/payments/calendar", params={"year": 2026, "month": 10}).json()
    assert (body["year"], body["month"], body["today"]) == (2026, 10, "2026-10-23")
    days = {d["day"]: d["items"] for d in body["days"]}
    assert list(days) == ["2026-10-10", "2026-10-25"]
    assert days["2026-10-10"][0]["status"] == "paid" and not days["2026-10-10"][0]["is_overdue"]
    assert sorted(i["name"] for i in days["2026-10-25"]) == ["Домен", "Сервер"]
    assert all(i["occurrence_id"] for items in days.values() for i in items)
    assert line(body | {"currencies": body["totals"]}, "RUB")["paid"] == "100.00"


def test_calendar_marks_overdue_unpaid(admin):
    create(admin, "Аренда", "100.00", "RUB", "2026-10-10")
    [item] = admin.get(f"{B}/payments/calendar", params={"year": 2026, "month": 10}).json()["days"][0]["items"]
    assert item["status"] == "unpaid" and item["is_overdue"] and item["overdue_days"] == 13


def test_calendar_future_months_are_planned_with_month_end_rules(admin):
    create(admin, "Подписка", "9.99", "EUR", "2026-01-31")

    feb = admin.get(f"{B}/payments/calendar", params={"year": 2027, "month": 2}).json()
    [day] = feb["days"]
    assert day["day"] == "2027-02-28"
    assert day["items"][0]["status"] == "planned" and day["items"][0]["occurrence_id"] is None
    assert not day["items"][0]["is_overdue"]
    assert line(feb | {"currencies": feb["totals"]}, "EUR")["planned"] == "9.99"

    mar = admin.get(f"{B}/payments/calendar", params={"year": 2027, "month": 3}).json()
    assert mar["days"][0]["day"] == "2027-03-31"


def test_calendar_defaults_to_current_month_and_hides_empty_days(admin):
    create(admin, "Сервер", "20.00", "USD", "2026-10-25")
    body = admin.get(f"{B}/payments/calendar").json()
    assert (body["year"], body["month"]) == (2026, 10) and len(body["days"]) == 1


def test_calendar_deleted_payments(admin):
    payment = create(admin, "Аренда", "100.00", "RUB", "2026-10-10")
    admin.delete(f"{B}/recurring-payments/{payment}")

    assert admin.get(f"{B}/payments/calendar", params={"year": 2026, "month": 10}).json()["days"] == []
    history = admin.get(f"{B}/payments/calendar", params={"year": 2026, "month": 10, "include_deleted": True}).json()
    assert history["days"][0]["items"][0]["payment_deleted"] is True
    # будущие месяцы удалённого платежа не планируются
    assert admin.get(f"{B}/payments/calendar", params={"year": 2027, "month": 1, "include_deleted": True}).json()["days"] == []


@pytest.mark.parametrize("params", [{"month": 13}, {"year": 1999}])
def test_calendar_validation(admin, params):
    assert admin.get(f"{B}/payments/calendar", params=params).status_code == 422
