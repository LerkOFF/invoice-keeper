from tests.helpers import B

URL = f"{B}/recurring-payments/import"


def upload(client, text: str, dry_run: bool = True, encoding: str = "utf-8"):
    files = {"file": ("payments.csv", text.encode(encoding), "text/csv")}
    return client.post(URL, params={"dry_run": str(dry_run).lower()}, files=files)


GOOD = (
    "Название;Сумма;Валюта;Первый срок;Периодичность;Категория;Ответственный;Ссылка на оплату;Реквизиты\n"
    "Аренда офиса;45 000,00;руб;18.11.2026;ежемесячно;Аренда;@ivan;;Договор 42\n"
    "Сервер Aeza;20;USD;2026-11-25;;IT;;https://my.aeza.ru;\n"
    "\n"
    "Домен;1290 ₽;RUB;07.12.2026;раз в год;IT;;;\n"
)


def test_template_is_csv_that_imports_cleanly(admin):
    response = admin.get(f"{URL}/template")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert "attachment" in response.headers["content-disposition"]
    assert response.text.startswith("﻿Название;Сумма;Валюта;Первый срок")
    preview = upload(admin, response.text).json()
    assert preview["valid"] == 3 and all(not row["errors"] for row in preview["rows"])


def test_preview_creates_nothing_and_normalizes_values(admin):
    result = upload(admin, GOOD).json()
    assert result["dry_run"] is True and result["valid"] == 3 and result["created"] == 0
    first, second, third = result["rows"]
    assert first["line"] == 2 and first["amount"] == "45000.00" and first["currency"] == "RUB"
    assert first["first_due_date"] == "2026-11-18" and first["assignee_login"] == "ivan"
    assert second["period"] == "monthly" and second["pay_url"] == "https://my.aeza.ru"
    assert third["line"] == 5 and third["period"] == "yearly" and third["amount"] == "1290.00"
    assert admin.get(f"{B}/recurring-payments").json() == []


def test_commit_creates_payments_periods_and_one_audit_entry(admin, user):
    result = upload(admin, GOOD, dry_run=False).json()
    assert result["created"] == 3
    payments = {p["name"]: p for p in admin.get(f"{B}/recurring-payments").json()}
    assert payments["Аренда офиса"]["assignee_login"] == "ivan"
    assert payments["Аренда офиса"]["pay_details"] == "Договор 42"
    assert payments["Сервер Aeza"]["category"] == "IT"
    assert {o["name"] for o in user.get(f"{B}/payment-occurrences").json()} == set(payments)
    entry = admin.get(f"{B}/audit-log", params={"action": "payment.import"}).json()[0]
    assert entry["details"]["count"] == 3 and entry["details"]["file"] == "payments.csv"


def test_rows_with_errors_block_the_whole_import(admin):
    text = (
        "Название,Сумма,Валюта,Первый срок,Периодичность,Ответственный,Ссылка на оплату\n"
        "Хостинг,abc,RUB,01.11.2026,,,\n"
        "Подписка,10,GBP,01.11.2026,,,\n"
        "Почта,10,EUR,31.02.2026,,,\n"
        "Склад,10,RUB,01.11.2026,раз в неделю,,\n"
        "Бухгалтер,10,RUB,01.11.2026,,petya,\n"
        ",10,RUB,01.11.2026,,,\n"
        "Сайт,10,RUB,01.11.2026,,,javascript:alert(1)\n"
        "Касса,0,RUB,01.11.2026,,,\n"
        "Банк,10,RUB,01.11.2026,,,\n"
    )
    result = upload(admin, text).json()
    errors = {row["line"]: " ".join(row["errors"]) for row in result["rows"]}
    assert result["valid"] == 1 and errors[10] == ""
    assert "не число" in errors[2]
    assert "валюта" in errors[3]
    assert "ДД.ММ.ГГГГ" in errors[4]
    assert "периодичность" in errors[5]
    assert "petya" in errors[6]
    two = upload(admin, "Название;Сумма;Валюта;Первый срок;Ответственный\nХостинг;99;GBP;10.11.2026;petya\n").json()
    assert len(two["rows"][0]["errors"]) == 2  # видны все ошибки строки сразу
    assert "название: не заполнено" in errors[7]
    assert "ссылка на оплату" in errors[8]
    assert "больше нуля" in errors[9]

    response = upload(admin, text, dry_run=False)
    assert response.status_code == 422
    assert admin.get(f"{B}/recurring-payments").json() == []


def test_duplicate_name_is_a_warning_not_an_error(admin):
    admin.post(
        f"{B}/recurring-payments",
        json={"name": "Аренда офиса", "amount": "1", "currency": "RUB", "first_due_date": "2026-11-18"},
    )
    rows = upload(admin, GOOD).json()["rows"]
    assert rows[0]["warnings"] == ["платёж с таким названием и валютой уже есть"] and not rows[0]["errors"]
    assert not rows[1]["warnings"]
    twice = GOOD + "Сервер Aeza;25;usd;01.12.2026;;;;;\n"
    assert upload(admin, twice).json()["rows"][-1]["warnings"] == ["повторяет строку 3"]


def test_cp1251_file_and_english_headers_are_read(admin):
    text = "name\tamount\tcurrency\tfirst_due_date\nАренда\t100.5\teur\t2026-11-01\n"
    row = upload(admin, text, encoding="cp1251").json()["rows"][0]
    assert row["name"] == "Аренда" and row["amount"] == "100.50" and row["currency"] == "EUR"


def test_broken_files_are_rejected(admin):
    assert upload(admin, "").status_code == 422
    missing = upload(admin, "Название;Сумма\nАренда;10\n")
    assert missing.status_code == 422 and "first_due_date" in missing.json()["detail"]
    assert upload(admin, "Название;Сумма;Валюта;Первый срок\n").status_code == 422
    huge = "Название;Сумма;Валюта;Первый срок\n" + "Аренда;10;RUB;01.11.2026\n" * 501
    assert "500" in upload(admin, huge).json()["detail"]


def test_only_admin_can_import(user, anon):
    assert upload(user, GOOD).status_code == 403
    assert user.get(f"{URL}/template").status_code == 403
    assert upload(anon, GOOD).status_code == 401
