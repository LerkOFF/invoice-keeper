import csv
import io

from tests.helpers import B


def create(admin, **body):
    payload = {"name": "Аренда", "amount": "45000.50", "currency": "RUB", "first_due_date": "2026-09-05", **body}
    response = admin.post(f"{B}/recurring-payments", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def rows(response):
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/csv")
    text = response.content.decode("utf-8")
    assert text.startswith("﻿")
    return list(csv.reader(io.StringIO(text[1:]), delimiter=";"))


def test_export_has_header_and_excel_friendly_values(admin, user):
    create(admin)
    sept = admin.get(f"{B}/payment-occurrences").json()[0]
    admin.patch(f"{B}/payment-occurrences/{sept['id']}", json={"status": "paid", "paid_at": "2026-09-07"})

    response = user.get(f"{B}/payment-occurrences/export")
    assert 'filename="invoice-keeper-2026-10-23.csv"' in response.headers["content-disposition"]
    table = rows(response)
    assert table[0][:4] == ["Платёж", "Сумма", "Валюта", "Срок"]
    assert table[1] == ["Аренда", "45000,50", "RUB", "05.09.2026", "оплачен", "07.09.2026", "2", "ежемесячно", "", "0", "", ""]
    assert table[2][4:7] == ["не оплачен", "", "18"]


def test_export_uses_list_filters(admin):
    create(admin)
    create(admin, name="Сервер", currency="USD", amount="20")
    table = rows(admin.get(f"{B}/payment-occurrences/export", params={"currency": "USD"}))
    assert {row[0] for row in table[1:]} == {"Сервер"}
    overdue = rows(admin.get(f"{B}/payment-occurrences/export", params={"overdue": "true"}))
    assert all(int(row[6]) > 0 for row in overdue[1:]) and len(overdue) > 1


def test_formula_like_names_are_escaped(admin):
    create(admin, name="=HYPERLINK(\"http://evil\")")
    table = rows(admin.get(f"{B}/payment-occurrences/export"))
    assert table[1][0].startswith("'=")


def test_export_needs_login(anon):
    assert anon.get(f"{B}/payment-occurrences/export").status_code == 401


def test_search_by_name_is_case_insensitive_for_cyrillic(admin, user):
    create(admin, name="Аренда офиса")
    create(admin, name="Сервер Aeza", currency="USD", amount="20")
    found = user.get(f"{B}/payment-occurrences", params={"q": "аРЕНДА"}).json()
    assert found and {o["name"] for o in found} == {"Аренда офиса"}
    assert user.get(f"{B}/payment-occurrences", params={"q": "aeza"}).json()[0]["name"] == "Сервер Aeza"
    assert user.get(f"{B}/payment-occurrences", params={"q": "нет такого"}).json() == []
    # поиск работает и в выгрузке
    table = rows(admin.get(f"{B}/payment-occurrences/export", params={"q": "сервер"}))
    assert {row[0] for row in table[1:]} == {"Сервер Aeza"}
