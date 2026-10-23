from datetime import timedelta

from sqlalchemy import select

from app.core.config import Settings
from app.models import PaymentOccurrence, ReminderDelivery
from app.services.reminders import send_due_reminders
from tests.fakes import FakeNotifier
from tests.test_reminders import SETTINGS, TODAY, add_payment


def run(db, channels, today=TODAY) -> int:
    return send_due_reminders(db, channels, SETTINGS, today)


def deliveries(db):
    return sorted((d.occurrence_id, d.channel) for d in db.scalars(select(ReminderDelivery)))


def test_every_configured_channel_gets_the_reminder_once(db):
    add_payment(db, TODAY + timedelta(days=1))
    tg, hook = FakeNotifier(name="telegram"), FakeNotifier(name="webhook")

    assert run(db, [tg, hook]) == 1
    assert run(db, [tg, hook]) == 0

    assert len(tg.messages) == 1 and len(hook.messages) == 1
    assert [c for _, c in deliveries(db)] == ["telegram", "webhook"]
    assert db.scalar(select(PaymentOccurrence.reminded_at)) is not None


def test_failure_of_one_channel_does_not_repeat_the_others(db):
    add_payment(db, TODAY + timedelta(days=1))
    tg, hook = FakeNotifier(name="telegram"), FakeNotifier(name="webhook", fail=True)

    assert run(db, [tg, hook]) == 1  # Telegram доставил
    assert [c for _, c in deliveries(db)] == ["telegram"]
    assert db.scalar(select(PaymentOccurrence.reminded_at)) is None  # период ещё в очереди

    assert run(db, [tg, hook]) == 0  # webhook всё ещё лежит, Telegram повторно не шлём
    assert len(tg.messages) == 1

    hook.fail = False
    assert run(db, [tg, hook]) == 1  # webhook доставлен
    assert len(tg.messages) == 1 and len(hook.messages) == 1
    assert db.scalar(select(PaymentOccurrence.reminded_at)) is not None
    assert run(db, [tg, hook]) == 0


def test_down_channel_is_not_hammered_within_a_run(db):
    add_payment(db, TODAY + timedelta(days=1), name="A")
    add_payment(db, TODAY + timedelta(days=2), name="B")
    calls = []

    class Counting(FakeNotifier):
        def send(self, reminder):
            calls.append(reminder.name)
            super().send(reminder)

    run(db, [Counting(name="webhook", fail=True), FakeNotifier(name="telegram")])
    assert len(calls) == 1  # после первого сбоя по этому каналу больше не пробуем


def test_unconfigured_channel_is_skipped_and_does_not_block(db):
    add_payment(db, TODAY + timedelta(days=1))
    tg, idle = FakeNotifier(name="telegram"), FakeNotifier(name="webhook", configured=False)

    assert run(db, [tg, idle]) == 1
    assert idle.messages == []
    assert db.scalar(select(PaymentOccurrence.reminded_at)) is not None


def test_channel_added_later_does_not_resend_old_reminders(db):
    add_payment(db, TODAY + timedelta(days=1))
    tg = FakeNotifier(name="telegram")
    run(db, [tg])

    late = FakeNotifier(name="webhook")
    assert run(db, [tg, late]) == 0  # период уже полностью напомнен
    assert late.messages == [] and len(tg.messages) == 1


def test_no_configured_channels_sends_nothing_and_keeps_queue(db):
    add_payment(db, TODAY + timedelta(days=1))
    assert run(db, [FakeNotifier(configured=False)]) == 0
    assert db.scalar(select(PaymentOccurrence.reminded_at)) is None
    assert run(db, [FakeNotifier()]) == 1  # после настройки уйдёт


def test_reminder_carries_structured_data_for_channels(db):
    add_payment(db, TODAY + timedelta(days=2), name="Сервер", amount="20", currency="USD")
    channel = FakeNotifier(name="webhook")
    run(db, [channel])

    [reminder] = channel.reminders
    assert (reminder.name, str(reminder.amount), reminder.currency, reminder.days_left) == ("Сервер", "20.00", "USD", 2)
    assert reminder.due_date == TODAY + timedelta(days=2) and not reminder.is_overdue
    assert "Сервер" in reminder.text


def test_overdue_reminder_is_flagged(db):
    add_payment(db, TODAY - timedelta(days=3))
    channel = FakeNotifier()
    run(db, [channel])
    assert channel.reminders[0].days_left == -3 and channel.reminders[0].is_overdue


def test_single_notifier_object_still_works(db):
    add_payment(db, TODAY + timedelta(days=1))
    assert send_due_reminders(db, FakeNotifier(), Settings(reminder_days=3), TODAY) == 1
