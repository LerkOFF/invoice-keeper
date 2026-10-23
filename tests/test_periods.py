from datetime import date
from decimal import Decimal

from app.models import Currency, RecurringPayment
from app.services.periods import due_date_for, ensure_occurrences


def make_payment(db, first_due: date) -> RecurringPayment:
    payment = RecurringPayment(name="Аренда", currency=Currency.RUB.value, first_due_date=first_due)
    payment.amount = Decimal("100.50")
    db.add(payment)
    db.flush()
    return payment


def test_due_date_clamps_to_last_day_and_returns_to_anchor():
    anchor = date(2026, 1, 31)
    assert due_date_for(anchor, 0) == date(2026, 1, 31)
    assert due_date_for(anchor, 1) == date(2026, 2, 28)
    assert due_date_for(anchor, 2) == date(2026, 3, 31)
    assert due_date_for(anchor, 3) == date(2026, 4, 30)


def test_due_date_leap_year_and_year_rollover():
    assert due_date_for(date(2028, 1, 31), 1) == date(2028, 2, 29)
    assert due_date_for(date(2026, 11, 15), 3) == date(2027, 2, 15)


def test_amount_roundtrip_in_minor_units():
    payment = RecurringPayment(name="x", currency="USD", first_due_date=date(2026, 1, 1))
    payment.amount = Decimal("9.99")
    assert payment.amount_minor == 999
    assert payment.amount == Decimal("9.99")


def test_generates_only_up_to_one_month_ahead(db):
    payment = make_payment(db, date(2026, 10, 25))
    created = ensure_occurrences(db, payment, today=date(2026, 10, 23))

    # горизонт 23 ноября, поэтому срок 25 ноября ещё не создаётся
    assert [o.due_date for o in created] == [date(2026, 10, 25)]


def test_next_period_appears_when_it_enters_horizon(db):
    payment = make_payment(db, date(2026, 10, 25))
    ensure_occurrences(db, payment, today=date(2026, 10, 23))
    db.flush()
    created = ensure_occurrences(db, payment, today=date(2026, 10, 26))

    assert [o.due_date for o in created] == [date(2026, 11, 25)]


def test_generation_is_idempotent(db):
    payment = make_payment(db, date(2026, 8, 5))
    first = ensure_occurrences(db, payment, today=date(2026, 10, 23))
    db.flush()
    second = ensure_occurrences(db, payment, today=date(2026, 10, 23))

    assert len(first) == 4  # 5 авг, 5 сен, 5 окт, 5 ноя
    assert second == []


def test_overdue_period_does_not_stop_next_ones(db):
    payment = make_payment(db, date(2026, 9, 5))
    ensure_occurrences(db, payment, today=date(2026, 10, 23))
    db.flush()
    dues = [o.due_date for o in payment.occurrences]
    assert dues == [date(2026, 9, 5), date(2026, 10, 5), date(2026, 11, 5)]


def test_deleted_payment_gets_no_new_periods(db):
    from datetime import datetime, timezone

    payment = make_payment(db, date(2026, 10, 25))
    payment.deleted_at = datetime.now(timezone.utc)
    assert ensure_occurrences(db, payment, today=date(2026, 10, 23)) == []
