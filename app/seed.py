from datetime import timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.clock import today as today_in_tz
from app.core.config import Settings
from app.core.security import hash_password
from app.models import Currency, OccurrenceStatus, RecurringPayment, User
from app.services.periods import ensure_occurrences


def seed_demo_data(db: Session, settings: Settings) -> bool:
    """Заполняет пустую базу тестовыми данными. Повторный вызов ничего не меняет.

    Сроки считаются от сегодняшнего дня, чтобы демо всегда показывало
    просрочку, ближайшее напоминание и историю оплат.
    """
    if db.scalar(select(func.count()).select_from(RecurringPayment)):
        return False

    today = today_in_tz()

    if not db.scalar(select(User).where(User.login == settings.seed_user_login)):
        db.add(User(login=settings.seed_user_login, password_hash=hash_password(settings.seed_user_password)))

    # Аренда в рублях: первый период оплачен вовремя, второй просрочен, третий впереди
    rent = RecurringPayment(
        name="Аренда офиса",
        currency=Currency.RUB.value,
        first_due_date=today - timedelta(days=35),
    )
    rent.amount = Decimal("45000.00")

    # Сервер в долларах: срок через 2 дня, значит напоминание уйдёт сразу
    server = RecurringPayment(
        name="Сервер Aeza",
        currency=Currency.USD.value,
        first_due_date=today + timedelta(days=2),
    )
    server.amount = Decimal("20.00")

    # Подписка в евро: срок далеко, напоминания ещё нет
    subscription = RecurringPayment(
        name="Подписка на сервис",
        currency=Currency.EUR.value,
        first_due_date=today + timedelta(days=12),
    )
    subscription.amount = Decimal("9.99")

    db.add_all([rent, server, subscription])
    db.flush()

    for payment in (rent, server, subscription):
        ensure_occurrences(db, payment, today)
    db.flush()

    first_rent_period = rent.occurrences[0]
    first_rent_period.status = OccurrenceStatus.PAID.value
    first_rent_period.paid_at = first_rent_period.due_date

    db.commit()
    return True
