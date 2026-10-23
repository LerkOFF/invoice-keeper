import pytest

from app.api.help_page import contacts_of
from app.core.config import Settings, get_settings
from tests.helpers import B


def test_help_needs_login(anon):
    assert anon.get(f"{B}/help").status_code == 401


def test_help_without_contacts_shows_settings(user):
    data = user.get(f"{B}/help").json()
    assert data["contacts"] == {"telegram": None, "email": None, "url": None}
    assert data["bots"] == {} and data["channels"] == []
    assert data["reminder_days"] == 3 and data["overdue_reminders"] is True and data["timezone"]


def test_help_returns_configured_contacts(app, user):
    app.dependency_overrides[get_settings] = lambda: Settings(
        support_telegram="@joulerkOFF",
        support_email="lerk@joulerk.ru",
        support_url="https://github.com/LerkOFF/invoice-keeper",
        reminder_days=5,
    )
    data = user.get(f"{B}/help").json()
    assert data["contacts"]["telegram"] == {"label": "@joulerkOFF", "url": "https://t.me/joulerkOFF"}
    assert data["contacts"]["email"] == {"label": "lerk@joulerk.ru", "url": "mailto:lerk@joulerk.ru"}
    assert data["contacts"]["url"] == {
        "label": "github.com/LerkOFF/invoice-keeper",
        "url": "https://github.com/LerkOFF/invoice-keeper",
    }
    assert data["reminder_days"] == 5


@pytest.mark.parametrize(
    "telegram, expected",
    [
        ("joulerkOFF", "@joulerkOFF"),
        ("https://t.me/joulerkOFF", "@joulerkOFF"),
        ("@bad name", None),
        ("javascript:alert(1)", None),
    ],
)
def test_telegram_contact_is_normalized(telegram, expected):
    contact = contacts_of(Settings(support_telegram=telegram)).telegram
    assert (contact.label if contact else None) == expected


@pytest.mark.parametrize("url", ["javascript:alert(1)", "ftp://host/file", "https://x.ru/a b", 'https://x.ru/"><script>'])
def test_unsafe_links_are_dropped(url):
    assert contacts_of(Settings(support_url=url, support_email="not-an-email")).url is None
    assert contacts_of(Settings(support_email="not-an-email")).email is None
