from datetime import date, datetime
from zoneinfo import ZoneInfo

from app.core.config import get_settings


def now() -> datetime:
    """Текущее время в едином часовом поясе приложения."""
    return datetime.now(ZoneInfo(get_settings().app_timezone))


def today() -> date:
    """«Сегодня» для всех расчётов сроков и просрочки."""
    return now().date()
