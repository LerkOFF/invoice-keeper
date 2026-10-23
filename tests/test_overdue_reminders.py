from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select

from app.core.config import Settings
from app.models import AuditEntry, OccurrenceStatus, OverdueDelivery
from tests.fakes import FakeNotifier
from tests.test_reminders import TODAY, add_payment, run

DUE = TODAY + timedelta(days=2)  # 25 октября
SETTINGS = Settings(reminder_days=3, app_timezone="Europe/Moscow")


def first_period(payment):
    return payment.occurrences[0]


def test_overdue_notice_goes_once_the_day_after_due(db):
    payment = add_payment(db, DUE)
    notifier = FakeNotifier()
    assert run(db, notifier, settings=SETTINGS) == 1  # обычное напоминание за 2 дня

    assert run(db, notifier, today=DUE, settings=SETTINGS) == 0  # в день срока ещё не просрочка
    assert run(db, notifier, today=DUE + timedelta(days=1), settings=SETTINGS) == 1
    notice = notifier.reminders[-1]
    assert notice.overdue_notice and "Платёж просрочен" in notice.text and "просрочен на 1 дн." in notice.text
    assert notice.occurrence_id == first_period(payment).id  # кнопка «Оплачено» ведёт на тот же период

    assert run(db, notifier, today=DUE + timedelta(days=5), settings=SETTINGS) == 0  # без повторов
    db.refresh(first_period(payment))
    assert first_period(payment).overdue_reminded_at is not None
    actions = list(db.scalars(select(AuditEntry.action)))
    assert actions.count("reminder.sent") == 1 and actions.count("reminder.overdue_sent") == 1


def test_paid_period_gets_no_overdue_notice(db):
    payment = add_payment(db, DUE)
    notifier = FakeNotifier()
    run(db, notifier, settings=SETTINGS)
    period = first_period(payment)
    period.status, period.paid_at = OccurrenceStatus.PAID.value, DUE
    db.commit()
    assert run(db, notifier, today=DUE + timedelta(days=1), settings=SETTINGS) == 0


def test_no_second_notice_when_first_reminder_was_already_late(db):
    add_payment(db, TODAY - timedelta(days=2))
    notifier = FakeNotifier()
    assert run(db, notifier, settings=SETTINGS) == 1 and "просрочен на 2 дн." in notifier.messages[0]
    assert run(db, notifier, today=TODAY + timedelta(days=1), settings=SETTINGS) == 0


def test_deleted_payment_and_disabled_setting_send_nothing(db):
    payment = add_payment(db, DUE)
    other = add_payment(db, DUE, name="Сервер")
    notifier = FakeNotifier()
    run(db, notifier, settings=SETTINGS)
    payment.deleted_at = datetime.now(UTC)
    db.commit()
    off = Settings(reminder_days=3, overdue_reminders=False)
    assert run(db, notifier, today=DUE + timedelta(days=1), settings=off) == 0
    assert run(db, notifier, today=DUE + timedelta(days=1), settings=SETTINGS) == 1
    assert notifier.reminders[-1].name == other.name


def test_failed_channel_is_retried_without_duplicating_others(db):
    add_payment(db, DUE)
    good, flaky = FakeNotifier(name="telegram"), FakeNotifier(name="email")
    run(db, [good, flaky], settings=SETTINGS)
    flaky.fail = True
    later = DUE + timedelta(days=1)
    assert run(db, [good, flaky], today=later, settings=SETTINGS) == 1
    flaky.fail = False
    assert run(db, [good, flaky], today=later, settings=SETTINGS) == 1  # дошло до email, telegram не повторяется
    assert run(db, [good, flaky], today=later, settings=SETTINGS) == 0
    assert [r.overdue_notice for r in good.reminders] == [False, True]
    assert [r.overdue_notice for r in flaky.reminders] == [False, True]
    assert {d.channel for d in db.scalars(select(OverdueDelivery))} == {"telegram", "email"}


def test_reminder_time_is_compared_in_app_timezone(db):
    payment = add_payment(db, DUE)
    period = first_period(payment)
    # 22:30 UTC 25 октября это уже 26 октября по Москве: напоминание пришло после срока
    period.reminded_at = datetime(2026, 10, 25, 22, 30, tzinfo=UTC)
    db.commit()
    assert run(db, FakeNotifier(), today=date(2026, 10, 27), settings=SETTINGS) == 0


def test_overdue_notice_has_own_email_subject_and_webhook_event():
    import json

    import httpx

    from app.services.mailer import build_email
    from tests.test_webhook import make, reminder

    notice = reminder(days_left=-1, overdue_notice=True, text="⚠️ Платёж просрочен")
    email = build_email(notice, Settings(smtp_from="bot@example.com", smtp_to="team@example.com"))
    assert email["Subject"].startswith("Платёж просрочен: Аренда")

    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["event"] = json.loads(request.content)["event"]
        return httpx.Response(200)

    make(handler).send(notice)
    assert seen["event"] == "reminder.overdue"
