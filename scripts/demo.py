"""Сквозная проверка по сценарию демонстрации из задания, против запущенного приложения.

    python3 scripts/demo.py                       # http://localhost:8000, учётки из .env.example
    python3 scripts/demo.py --base http://host:8000 --admin-password '...'
    python3 scripts/demo.py --keep                # не прекращать созданные демо-платежи

Нужен только Python 3.9+, без зависимостей. Шаги:
  1. вход администратором            5. просроченный платёж
  2. добавление регулярного платежа  6. исправление фактической даты оплаты
  3. напоминание в Telegram          7. следующий период с отдельным статусом
  4. вход пользователем, оплата
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from datetime import date, timedelta

PASSED = 0


class Client:
    def __init__(self, base: str) -> None:
        self.base = base.rstrip("/") + "/api/v1"
        self.token: str | None = None

    def call(self, method: str, path: str, body=None, expect: int | tuple = (200, 201, 204)):
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(self.base + path, data=data, method=method)
        if data:
            request.add_header("Content-Type", "application/json")
        if self.token:
            request.add_header("Authorization", f"Bearer {self.token}")
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                status, raw = response.status, response.read()
        except urllib.error.HTTPError as error:
            status, raw = error.code, error.read()
        expected = (expect,) if isinstance(expect, int) else expect
        if status not in expected:
            fail(f"{method} {path}: ждали {expected}, получили {status}: {raw.decode()[:200]}")
        return json.loads(raw) if raw else None

    def login(self, login: str, password: str) -> dict:
        result = self.call("POST", "/auth/login", {"login": login, "password": password})
        self.token = result["token"]
        return result["user"]


def fail(message: str) -> None:
    print(f"  ✗ {message}")
    sys.exit(1)


def check(condition: bool, message: str) -> None:
    global PASSED
    if not condition:
        fail(message)
    PASSED += 1
    print(f"  ✓ {message}")


def step(number: int, title: str) -> None:
    print(f"\n{number}. {title}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base", default="http://localhost:8000")
    parser.add_argument("--admin-login", default="admin")
    parser.add_argument("--admin-password", default="change-me")
    parser.add_argument("--user-login", default="user")
    parser.add_argument("--user-password", default="user-pass-123")
    parser.add_argument("--keep", action="store_true", help="не прекращать созданные демо-платежи")
    parser.add_argument("--require-telegram", action="store_true", help="считать ошибкой, если напоминание не ушло")
    args = parser.parse_args()

    admin, user, anon = Client(args.base), Client(args.base), Client(args.base)
    stamp = time.strftime("%H%M%S")
    created: list[int] = []

    print(f"Демо-проверка: {args.base}")

    step(0, "Без авторизации данные недоступны")
    check(anon.call("GET", "/payment-occurrences", expect=401) is not None, "список платежей без входа: 401")
    anon.call("GET", "/users", expect=401)
    check(True, "список пользователей без входа: 401")

    step(1, "Вход администратором")
    me = admin.login(args.admin_login, args.admin_password)
    check(me["role"] == "admin", f"вошли как {me['login']}, роль admin")
    today = date.fromisoformat(admin.call("GET", "/payments/summary")["as_of"])

    step(2, "Добавление регулярного платежа")
    hosting = admin.call(
        "POST",
        "/recurring-payments",
        {"name": f"Демо хостинг {stamp}", "amount": "990.00", "currency": "USD", "first_due_date": (today + timedelta(days=2)).isoformat()},
    )
    created.append(hosting["id"])
    first = admin.call("GET", f"/payment-occurrences?recurring_id={hosting['id']}")[0]
    check(first["status"] == "unpaid" and first["due_date"] == (today + timedelta(days=2)).isoformat(), f"создан платёж, срок {first['due_date']}, статус «не оплачен»")

    step(3, "Напоминание в Telegram")
    reminded = None
    for _ in range(20):
        reminded = admin.call("GET", f"/payment-occurrences/{first['id']}")["reminded_at"]
        if reminded:
            break
        time.sleep(1)
    if reminded:
        check(True, f"напоминание отправлено ({reminded}), срок через 2 дня попадает в окно 3 дней")
    elif args.require_telegram:
        fail("напоминание не ушло: проверьте TELEGRAM_BOT_TOKEN и TELEGRAM_CHAT_ID")
    else:
        print("  • Telegram не настроен или недоступен: напоминание не ушло (укажите токен и чат в .env)")

    step(4, "Вход пользователем и отметка оплаты")
    me = user.login(args.user_login, args.user_password)
    check(me["role"] == "user", f"вошли как {me['login']}, роль user")
    user.call("POST", "/recurring-payments", {"name": "x", "amount": "1", "currency": "RUB", "first_due_date": today.isoformat()}, expect=403)
    user.call("POST", "/users", {"login": "hacker", "password": "hacker-pass-1"}, expect=403)
    user.call("DELETE", f"/recurring-payments/{hosting['id']}", expect=403)
    check(True, "пользователь не может ни создавать и удалять платежи, ни управлять пользователями (403)")
    paid = user.call("PATCH", f"/payment-occurrences/{first['id']}", {"status": "paid"})
    check(paid["status"] == "paid" and paid["paid_at"] == today.isoformat() and not paid["is_overdue"], "оплата отмечена сегодняшней датой, просрочки нет")
    cancelled = user.call("PATCH", f"/payment-occurrences/{first['id']}", {"status": "unpaid"})
    check(cancelled["status"] == "unpaid" and cancelled["paid_at"] is None, "отмена оплаты очищает дату")
    user.call("PATCH", f"/payment-occurrences/{first['id']}", {"status": "paid"})

    step(5, "Просроченный платёж")
    rent = admin.call(
        "POST",
        "/recurring-payments",
        {"name": f"Демо аренда {stamp}", "amount": "45000", "currency": "RUB", "first_due_date": (today - timedelta(days=5)).isoformat()},
    )
    created.append(rent["id"])
    overdue = user.call("GET", f"/payment-occurrences?recurring_id={rent['id']}&overdue=true")
    check(len(overdue) == 1 and overdue[0]["overdue_days"] == 5, "период просрочен на 5 дней, виден в фильтре «просрочено»")
    summary = user.call("GET", "/payments/summary")
    rub = next(c for c in summary["currencies"] if c["currency"] == "RUB")
    check(rub["count_overdue"] >= 1 and [c["currency"] for c in summary["currencies"]] == ["RUB", "USD", "EUR"], "итоги считаются отдельно по RUB, USD, EUR, просрочка видна в RUB")

    step(6, "Исправление фактической даты оплаты")
    late = user.call("PATCH", f"/payment-occurrences/{overdue[0]['id']}", {"status": "paid"})
    check(late["is_overdue"] and late["overdue_days"] == 5, "отметили сегодня: оплата позже срока, просрочка 5 дней")
    fixed = user.call("PATCH", f"/payment-occurrences/{overdue[0]['id']}", {"paid_at": overdue[0]["due_date"]})
    check(not fixed["is_overdue"] and fixed["due_date"] == overdue[0]["due_date"], "дата исправлена на срок: просрочка исчезла, срок не изменился")

    step(7, "Следующий период с отдельным статусом")
    periods = admin.call("GET", f"/payment-occurrences?recurring_id={rent['id']}")
    check(len(periods) >= 2, f"у аренды {len(periods)} периода: {', '.join(p['due_date'] for p in periods)}")
    check(periods[0]["status"] == "paid" and periods[1]["status"] == "unpaid", "прошлый период оплачен и сохранён, следующий неоплачен: статусы раздельные")

    step(8, "Удаление платежа")
    if not args.keep:
        for payment_id in created:
            admin.call("DELETE", f"/recurring-payments/{payment_id}")
        gone = admin.call("GET", "/recurring-payments")
        check(not any(p["id"] in created for p in gone), "прекращённые платежи пропали из списка")
        history = admin.call("GET", f"/payment-occurrences?recurring_id={rent['id']}&include_deleted=true")
        check(len(history) >= 2 and history[0]["paid_at"], "история оплат сохранилась")
    else:
        print("  • --keep: демо-платежи оставлены")

    print(f"\nГотово: {PASSED} проверок пройдено")


if __name__ == "__main__":
    main()
