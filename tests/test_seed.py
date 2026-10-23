from sqlalchemy import func, select

from app.core.config import Settings
from app.core.clock import today
from app.models import OccurrenceStatus, PaymentOccurrence, RecurringPayment, User
from app.seed import seed_demo_data


def test_seed_creates_three_currencies_user_and_history(db):
    settings = Settings(seed_user_login="demo", seed_user_password="demo-pass-123")

    assert seed_demo_data(db, settings) is True

    currencies = set(db.scalars(select(RecurringPayment.currency)))
    assert currencies == {"RUB", "USD", "EUR"}
    assert db.scalar(select(User).where(User.login == "demo")) is not None

    occurrences = list(db.scalars(select(PaymentOccurrence)))
    paid = [o for o in occurrences if o.status == OccurrenceStatus.PAID.value]
    overdue = [
        o for o in occurrences if o.status == OccurrenceStatus.UNPAID.value and o.due_date < today()
    ]
    assert len(paid) == 1 and paid[0].paid_at == paid[0].due_date
    assert len(overdue) == 1


def test_seed_is_idempotent(db):
    settings = Settings()
    assert seed_demo_data(db, settings) is True
    before = db.scalar(select(func.count()).select_from(PaymentOccurrence))

    assert seed_demo_data(db, settings) is False
    assert db.scalar(select(func.count()).select_from(PaymentOccurrence)) == before
