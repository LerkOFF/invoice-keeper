import threading
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import delete, select

from app.core.config import Settings
from app.core.db import SessionLocal
from app.models import Currency, OccurrenceStatus, PaymentOccurrence, RecurringPayment
from app.services.periods import ensure_occurrences
from app.services.reminders import build_message, format_money, run_reminders, send_due_reminders
from tests.fakes import FakeNotifier

TODAY = date(2026, 10, 23)
SETTINGS = Settings(reminder_days=3)


def add_payment(db, due: date, name="Аренда", amount="45000.00", currency="RUB", today=TODAY):
    payment = RecurringPayment(name=name, currency=currency, first_due_date=due)
    payment.amount = Decimal(amount)
    db.add(payment)
    db.flush()
    ensure_occurrences(db, payment, today)
    db.commit()
    return payment


def run(db, notifier, today=TODAY, settings=SETTINGS) -> int:
    return send_due_reminders(db, notifier, settings, today)


def test_reminds_three_days_before_due(db):
    add_payment(db, TODAY + timedelta(days=3))
    notifier = FakeNotifier()

    assert run(db, notifier) == 1
    message = notifier.messages[0]
    assert "Аренда" in message and "45 000.00 RUB" in message and "26.10.2026" in message


def test_does_not_remind_earlier_than_three_days(db):
    add_payment(db, TODAY + timedelta(days=4))
    notifier = FakeNotifier()
    assert run(db, notifier) == 0 and notifier.messages == []


def test_reminds_when_exactly_the_window_opens(db):
    add_payment(db, TODAY + timedelta(days=4))
    notifier = FakeNotifier()
    run(db, notifier, today=TODAY)
    assert run(db, notifier, today=TODAY + timedelta(days=1)) == 1


def test_no_duplicates_on_repeated_runs(db):
    add_payment(db, TODAY + timedelta(days=2))
    notifier = FakeNotifier()

    assert run(db, notifier) == 1
    assert run(db, notifier) == 0
    assert run(db, notifier, today=TODAY + timedelta(days=1)) == 0
    assert len(notifier.messages) == 1
    assert db.scalar(select(PaymentOccurrence.reminded_at)) is not None


def test_added_late_reminds_immediately(db):
    add_payment(db, TODAY + timedelta(days=1))
    notifier = FakeNotifier()
    assert run(db, notifier) == 1
    assert "завтра" in notifier.messages[0]


def test_paid_period_is_not_reminded(db):
    payment = add_payment(db, TODAY + timedelta(days=1))
    occurrence = payment.occurrences[0]
    occurrence.status = OccurrenceStatus.PAID.value
    occurrence.paid_at = TODAY
    db.commit()

    notifier = FakeNotifier()
    assert run(db, notifier) == 0 and notifier.messages == []


def test_cancelled_payment_becomes_eligible_again_if_never_reminded(db):
    payment = add_payment(db, TODAY + timedelta(days=1))
    occurrence = payment.occurrences[0]
    occurrence.status = OccurrenceStatus.PAID.value
    occurrence.paid_at = TODAY
    db.commit()
    notifier = FakeNotifier()
    run(db, notifier)

    occurrence.status = OccurrenceStatus.UNPAID.value
    occurrence.paid_at = None
    db.commit()
    assert run(db, notifier) == 1


def test_deleted_payment_does_not_remind(db):
    payment = add_payment(db, TODAY + timedelta(days=1))
    payment.deleted_at = datetime.now(UTC)
    db.commit()

    notifier = FakeNotifier()
    assert run(db, notifier) == 0 and notifier.messages == []


def test_payment_deleted_after_reminder_stays_quiet_for_next_periods(db):
    payment = add_payment(db, TODAY + timedelta(days=1))
    run(db, FakeNotifier())
    payment.deleted_at = datetime.now(UTC)
    db.commit()

    notifier = FakeNotifier()
    later = TODAY + timedelta(days=40)
    ensure_occurrences(db, payment, later)
    db.commit()
    assert run(db, notifier, today=later) == 0


def test_next_period_gets_its_own_reminder(db):
    payment = add_payment(db, TODAY + timedelta(days=1))
    notifier = FakeNotifier()
    run(db, notifier)

    later = date(2026, 11, 24)  # через три дня до следующего срока 24 ноября
    ensure_occurrences(db, payment, later + timedelta(days=0))
    db.commit()
    assert run(db, notifier, today=date(2026, 11, 21)) == 1
    assert len(notifier.messages) == 2


def test_overdue_unpaid_is_reminded_once(db):
    add_payment(db, TODAY - timedelta(days=2))
    notifier = FakeNotifier()

    assert run(db, notifier) == 1 and "просрочен на 2 дн." in notifier.messages[0]
    assert run(db, notifier) == 0


def test_failure_keeps_period_pending_and_next_run_delivers_once(db):
    add_payment(db, TODAY + timedelta(days=2))
    broken = FakeNotifier(fail=True)

    assert run(db, broken) == 0
    assert db.scalar(select(PaymentOccurrence.reminded_at)) is None

    working = FakeNotifier()
    assert run(db, working) == 1
    assert run(db, working) == 0
    assert len(working.messages) == 1


def test_failure_does_not_hammer_other_periods(db):
    add_payment(db, TODAY + timedelta(days=1), name="A")
    add_payment(db, TODAY + timedelta(days=2), name="B")
    calls = []

    class Counting(FakeNotifier):
        def send(self, text, **kwargs):
            calls.append(text)
            super().send(text, **kwargs)

    assert run(db, Counting(fail=True)) == 0
    assert len(calls) == 1


def test_not_configured_sends_nothing_and_keeps_periods_pending(db):
    add_payment(db, TODAY + timedelta(days=1))
    notifier = FakeNotifier(configured=False)

    assert run(db, notifier) == 0
    assert db.scalar(select(PaymentOccurrence.reminded_at)) is None
    # после настройки Telegram напоминание уйдёт
    assert run(db, FakeNotifier()) == 1


def test_reminder_days_setting_is_respected(db):
    add_payment(db, TODAY + timedelta(days=5))
    notifier = FakeNotifier()
    assert run(db, notifier, settings=Settings(reminder_days=3)) == 0
    assert run(db, notifier, settings=Settings(reminder_days=7)) == 1


def test_each_due_period_gets_one_message(db):
    add_payment(db, TODAY + timedelta(days=1), name="A", currency="USD", amount="20")
    add_payment(db, TODAY + timedelta(days=3), name="B", currency="EUR", amount="9.99")
    notifier = FakeNotifier()

    assert run(db, notifier) == 2
    assert "20.00 USD" in notifier.messages[0] and "9.99 EUR" in notifier.messages[1]


@pytest.mark.parametrize(
    ("amount", "expected"),
    [(Decimal("45000.00"), "45 000.00 RUB"), (Decimal("9.99"), "9.99 RUB"), (Decimal("1234567.5"), "1 234 567.50 RUB")],
)
def test_money_format(amount, expected):
    assert format_money(amount, "RUB") == expected


def test_message_phrases(db):
    payment = add_payment(db, TODAY)
    assert "сегодня" in build_message(payment.occurrences[0], TODAY)
    assert "через 2 дн." in build_message(payment.occurrences[0], TODAY - timedelta(days=2))


def test_parallel_runs_send_each_reminder_exactly_once():
    """Планировщик и задача «сразу после создания» могут стартовать одновременно."""
    with SessionLocal() as db:
        for model in (PaymentOccurrence, RecurringPayment):
            db.execute(delete(model))
        db.commit()
        add_payment(db, TODAY + timedelta(days=1), name="A")
        add_payment(db, TODAY + timedelta(days=2), name="B")

    notifier = FakeNotifier(delay=0.05)
    results: list[int] = []
    threads = [
        threading.Thread(target=lambda: results.append(run_reminders(SessionLocal, notifier, SETTINGS, TODAY)))
        for _ in range(4)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert sorted(m.split("\n")[2] for m in notifier.messages) == ["Платёж: A", "Платёж: B"]
    assert sum(results) == 2


def test_each_reminder_gets_a_pay_button_for_its_period(db):
    payment = add_payment(db, TODAY + timedelta(days=1))
    notifier = FakeNotifier()
    run(db, notifier)
    assert notifier.buttons == [payment.occurrences[0].id]
