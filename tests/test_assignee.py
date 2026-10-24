from datetime import timedelta
from decimal import Decimal

from app.core.config import Settings
from app.core.db import SessionLocal
from app.models import MessengerLink, RecurringPayment, User
from app.services.links import PersonalNotifier
from app.services.periods import ensure_occurrences
from app.services.reminders import send_due_reminders
from tests.fakes import FakeNotifier
from tests.helpers import B, TODAY, USER


def user_id(login=USER["login"]):
    with SessionLocal() as db:
        return db.query(User).filter_by(login=login).one().id


def create(admin, **extra):
    body = {"name": "Сервер", "amount": "20", "currency": "USD", "first_due_date": "2026-10-25", **extra}
    response = admin.post(f"{B}/recurring-payments", json=body)
    assert response.status_code == 201, response.text
    return response.json()


def test_assignee_is_set_shown_and_filtered(admin, user):
    ivan = user_id()
    mine = create(admin, name="Сервер", assignee_id=ivan)
    create(admin, name="Аренда", currency="RUB", amount="100")
    assert mine["assignee_id"] == ivan and mine["assignee_login"] == USER["login"]

    names = lambda client, **p: {o["name"] for o in client.get(f"{B}/payment-occurrences", params=p).json()}  # noqa: E731
    assert names(user, assignee="me") == {"Сервер"}
    assert names(admin, assignee=str(ivan)) == {"Сервер"}
    assert names(admin, assignee="-") == {"Аренда"}
    assert names(admin, assignee="me") == set()  # у админа из .env своих платежей нет
    assert admin.get(f"{B}/payment-occurrences", params={"assignee": "bob"}).status_code == 422
    period = user.get(f"{B}/payment-occurrences", params={"assignee": "me"}).json()[0]
    assert period["assignee_login"] == USER["login"]


def test_only_regular_users_can_be_assignees(admin):
    body = {"name": "x", "amount": "1", "currency": "RUB", "first_due_date": "2026-10-25", "assignee_id": 99999}
    response = admin.post(f"{B}/recurring-payments", json=body)
    assert response.status_code == 422 and "Ответственный" in response.json()["detail"]


def test_assignee_is_changed_cleared_and_dropped_with_user(admin):
    payment = create(admin, assignee_id=user_id())
    url = f"{B}/recurring-payments/{payment['id']}"
    assert admin.patch(url, json={"assignee_id": None}).json()["assignee_id"] is None
    admin.patch(url, json={"assignee_id": user_id()})
    assert admin.delete(f"{B}/users/{user_id()}").status_code == 204
    after = [p for p in admin.get(f"{B}/recurring-payments").json() if p["id"] == payment["id"]][0]
    assert after["assignee_id"] is None  # пользователь удалён, платёж остался без ответственного


def _link(db, owner_id=None, admin=False, chat="100"):
    link = MessengerLink(messenger="telegram", user_id=owner_id, is_admin=admin, external_user_id=chat, chat_id=chat, display_name="x")
    db.add(link)
    db.flush()
    return link


class _Personal(PersonalNotifier):
    """Личный канал без сети: копит сообщения, как FakeNotifier."""

    def __init__(self, link, settings):
        super().__init__(link, settings)
        self.reminders = []

    @property
    def configured(self) -> bool:
        return True

    def send(self, reminder):
        self.reminders.append(reminder)


def test_personal_reminders_go_to_assignee_and_admin_only(db):
    settings = Settings(reminder_days=3)
    ivan, olga = User(login="ivan2", password_hash="x"), User(login="olga", password_hash="x")
    db.add_all([ivan, olga])
    db.flush()
    payment = RecurringPayment(name="Сервер", currency="USD", first_due_date=TODAY + timedelta(days=2), assignee_id=ivan.id)
    payment.amount = Decimal("20")
    db.add(payment)
    db.flush()
    ensure_occurrences(db, payment, TODAY)
    channels = {
        "ivan": _Personal(_link(db, ivan.id, chat="1"), settings),
        "olga": _Personal(_link(db, olga.id, chat="2"), settings),
        "admin": _Personal(_link(db, admin=True, chat="3"), settings),
    }
    db.commit()
    group = FakeNotifier()

    assert send_due_reminders(db, [group, *channels.values()], settings, TODAY, personal=False) == 1
    assert len(group.reminders) == 1  # общий чат получает всё
    assert len(channels["ivan"].reminders) == 1 and len(channels["admin"].reminders) == 1
    assert channels["olga"].reminders == []
    # период доставлен всем, кого он касается: повторного прохода нет
    assert send_due_reminders(db, [group, *channels.values()], settings, TODAY, personal=False) == 0
    assert payment.occurrences[0].reminded_at is not None
