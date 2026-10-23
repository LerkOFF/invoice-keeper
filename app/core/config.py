from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    admin_login: str = "admin"
    admin_password: str = "change-me"

    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    telegram_api_base: str = "https://api.telegram.org"
    # Кнопка «Оплачено» в напоминании и приём нажатий (long polling)
    telegram_buttons_enabled: bool = True
    # Если задан, нажимать могут только эти Telegram id (через запятую), и то лишь будучи участниками чата
    telegram_allowed_user_ids: str = ""
    telegram_poll_timeout: int = 8

    app_timezone: str = "Europe/Moscow"
    reminder_days: int = 3
    scheduler_enabled: bool = True
    scheduler_interval_seconds: float = 60
    session_ttl_hours: int = 12
    cookie_secure: bool = False
    database_url: str = "sqlite:///./data/invoice_keeper.db"

    seed_demo_data: bool = True
    seed_user_login: str = "user"
    seed_user_password: str = "user-pass-123"

    @property
    def allowed_telegram_ids(self) -> set[int]:
        return {int(part) for part in self.telegram_allowed_user_ids.replace(";", ",").split(",") if part.strip()}


@lru_cache
def get_settings() -> Settings:
    return Settings()
