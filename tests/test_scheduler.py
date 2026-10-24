import asyncio
import time
from datetime import timedelta
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app import main as main_module
from app.api.deps import get_notifiers
from app.core.config import Settings
from app.core.db import SessionLocal
from app.models import PaymentOccurrence, RecurringPayment
from app.scheduler import scheduler_loop, tick
from app.services.periods import ensure_occurrences
from tests.fakes import FakeNotifier
from tests.helpers import ADMIN, B, TODAY, USER
from tests.conftest import logged_in


def with_notifier(app, notifier):
    app.dependency_overrides[get_notifiers] = lambda: [notifier]
    return app


def new_payment(client, due, name="Сервер"):
    response = client.post(
        f"{B}/recurring-payments",
        json={"name": name, "amount": "20.00", "currency": "USD", "first_due_date": due.isoformat()},
    )
    assert response.status_code == 201, response.text


# ---------- напоминание сразу при создании ----------


def test_payment_added_late_triggers_immediate_reminder(app):
    notifier = FakeNotifier()
    client = logged_in(with_notifier(app, notifier), ADMIN)

    new_payment(client, TODAY + timedelta(days=2))

    assert len(notifier.messages) == 1 and "Сервер" in notifier.messages[0]
    client.__exit__(None, None, None)


def test_payment_far_from_due_does_not_trigger_reminder(app):
    notifier = FakeNotifier()
    client = logged_in(with_notifier(app, notifier), ADMIN)

    new_payment(client, TODAY + timedelta(days=10))

    assert notifier.messages == []
    client.__exit__(None, None, None)


def test_telegram_failure_does_not_break_payment_creation(app):
    notifier = FakeNotifier(fail=True)
    client = logged_in(with_notifier(app, notifier), ADMIN)

    new_payment(client, TODAY + timedelta(days=1))  # 201 даже при недоступном Telegram

    assert len(client.get(f"{B}/recurring-payments").json()) == 1
    # планировщик потом доставит
    notifier.fail = False
    tick(SessionLocal, notifier, Settings(), TODAY)
    assert len(notifier.messages) == 1
    client.__exit__(None, None, None)


def test_forbidden_create_sends_nothing(app):
    notifier = FakeNotifier()
    client = logged_in(with_notifier(app, notifier), USER)

    response = client.post(
        f"{B}/recurring-payments",
        json={"name": "x", "amount": "1", "currency": "USD", "first_due_date": TODAY.isoformat()},
    )
    assert response.status_code == 403 and notifier.messages == []
    client.__exit__(None, None, None)


# ---------- проход планировщика ----------


def test_tick_reminds_when_window_opens_and_only_once():
    with SessionLocal() as db:
        payment = RecurringPayment(name="Аренда", currency="RUB", first_due_date=TODAY + timedelta(days=10))
        payment.amount = Decimal("100")
        db.add(payment)
        db.flush()
        ensure_occurrences(db, payment, TODAY)
        db.commit()

    notifier = FakeNotifier()
    settings = Settings()
    assert tick(SessionLocal, notifier, settings, TODAY) == 0
    assert tick(SessionLocal, notifier, settings, TODAY + timedelta(days=7)) == 1
    assert tick(SessionLocal, notifier, settings, TODAY + timedelta(days=7)) == 0
    assert tick(SessionLocal, notifier, settings, TODAY + timedelta(days=8)) == 0


def test_tick_holds_reminders_until_reminder_hour_but_creates_periods():
    with SessionLocal() as db:
        payment = RecurringPayment(name="Аренда", currency="RUB", first_due_date=TODAY + timedelta(days=1))
        payment.amount = Decimal("100")
        db.add(payment)
        db.flush()
        db.commit()

    notifier = FakeNotifier()
    settings = Settings(reminder_hour=9)
    assert tick(SessionLocal, notifier, settings, TODAY, hour=0) == 0
    assert notifier.messages == []
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(PaymentOccurrence)) == 1  # период создан ночью
    assert tick(SessionLocal, notifier, settings, TODAY, hour=8) == 0
    assert tick(SessionLocal, notifier, settings, TODAY, hour=9) == 1


def test_reminder_hour_zero_sends_any_time():
    with SessionLocal() as db:
        payment = RecurringPayment(name="Аренда", currency="RUB", first_due_date=TODAY + timedelta(days=1))
        payment.amount = Decimal("100")
        db.add(payment)
        db.flush()
        ensure_occurrences(db, payment, TODAY)
        db.commit()
    assert tick(SessionLocal, FakeNotifier(), Settings(reminder_hour=0), TODAY, hour=0) == 1


def test_tick_generates_missing_periods():
    with SessionLocal() as db:
        payment = RecurringPayment(name="Подписка", currency="EUR", first_due_date=TODAY)
        payment.amount = Decimal("9.99")
        db.add(payment)
        db.flush()
        ensure_occurrences(db, payment, TODAY)
        db.commit()
        before = db.scalar(select(func.count()).select_from(PaymentOccurrence))

    tick(SessionLocal, FakeNotifier(), Settings(), TODAY + timedelta(days=70))

    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(PaymentOccurrence)) > before


# ---------- цикл ----------


def test_loop_survives_job_errors_and_keeps_running():
    calls = []

    def job():
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("сбой прохода")

    async def scenario():
        task = asyncio.create_task(scheduler_loop(job, 0.01))
        await asyncio.sleep(0.15)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    asyncio.run(scenario())
    assert len(calls) >= 3  # после ошибки цикл продолжил работать


def test_app_runs_scheduler_in_background_and_stops_cleanly(monkeypatch):
    with SessionLocal() as db:
        payment = RecurringPayment(name="Фон", currency="RUB", first_due_date=TODAY + timedelta(days=1))
        payment.amount = Decimal("5")
        db.add(payment)
        db.flush()
        ensure_occurrences(db, payment, TODAY)
        db.commit()

    notifier = FakeNotifier()
    monkeypatch.setattr(
        main_module,
        "get_settings",
        lambda: Settings(scheduler_enabled=True, scheduler_interval_seconds=0.05, reminder_hour=0),
    )
    monkeypatch.setattr(main_module, "build_notifiers", lambda _settings: [notifier])
    monkeypatch.setattr(main_module, "today", lambda: TODAY)

    with TestClient(main_module.create_app()):
        deadline = time.time() + 3
        while not notifier.messages and time.time() < deadline:
            time.sleep(0.02)
        time.sleep(0.2)  # несколько проходов подряд: дублей быть не должно

    assert len(notifier.messages) == 1 and "Фон" in notifier.messages[0]
