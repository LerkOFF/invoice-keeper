import csv
import io

from tests.helpers import B


def create(admin, name, category=None, currency="RUB", amount="100", due="2026-10-25"):
    body = {"name": name, "amount": amount, "currency": currency, "first_due_date": due}
    if category is not None:
        body["category"] = category
    response = admin.post(f"{B}/recurring-payments", json=body)
    assert response.status_code == 201, response.text
    return response.json()


def test_category_is_normalized_saved_and_shown(admin, user):
    payment = create(admin, "Аренда офиса", category="  Аренда   и  офис ")
    assert payment["category"] == "Аренда и офис"
    assert user.get(f"{B}/payment-occurrences").json()[0]["category"] == "Аренда и офис"
    assert create(admin, "Без категории", category="   ")["category"] is None


def test_filter_by_category_and_without_category(admin):
    create(admin, "Аренда офиса", category="Аренда")
    create(admin, "Сервер", category="IT", currency="USD", amount="20")
    create(admin, "Разное")
    names = lambda **p: {o["name"] for o in admin.get(f"{B}/payment-occurrences", params=p).json()}  # noqa: E731
    assert names(category="IT") == {"Сервер"}
    assert names(category="-") == {"Разное"}
    rows = list(csv.reader(io.StringIO(admin.get(f"{B}/payment-occurrences/export", params={"category": "Аренда"}).text[1:]), delimiter=";"))
    assert rows[0][-1] == "Категория" and rows[1][-1] == "Аренда" and len(rows) == 2


def test_category_is_edited_and_cleared(admin):
    payment = create(admin, "Сервер", category="IT")
    url = f"{B}/recurring-payments/{payment['id']}"
    assert admin.patch(url, json={"category": "Хостинг"}).json()["category"] == "Хостинг"
    assert admin.patch(url, json={"category": None}).json()["category"] is None
    assert admin.patch(url, json={"category": "x" * 61}).status_code == 422


def test_budget_is_split_by_category_per_currency(admin):
    create(admin, "Аренда офиса", category="Аренда", amount="45000")
    create(admin, "Склад", category="Аренда", amount="5000")
    create(admin, "Сервер", category="IT", currency="USD", amount="20")
    create(admin, "Разное", amount="10")
    budget = admin.get(f"{B}/payments/budget", params={"year": 2026, "month": 10}).json()
    by_name = {c["category"]: {line["currency"]: line["planned"] for line in c["currencies"]} for c in budget["categories"]}
    assert [c["category"] for c in budget["categories"]] == ["IT", "Аренда", None]  # без категории последними
    assert by_name["Аренда"]["RUB"] == "50000.00" and by_name["IT"]["USD"] == "20.00" and by_name[None]["RUB"] == "10.00"
