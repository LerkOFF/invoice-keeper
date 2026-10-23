from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    admin_login: str = "admin"
    admin_password: str = "change-me"

    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    app_timezone: str = "Europe/Moscow"
    reminder_days: int = 3
    secret_key: str = "change-me"
    session_ttl_hours: int = 12
    cookie_secure: bool = False
    database_url: str = "sqlite:///./data/invoice_keeper.db"

    seed_demo_data: bool = True
    seed_user_login: str = "user"
    seed_user_password: str = "user-pass-123"


@lru_cache
def get_settings() -> Settings:
    return Settings()
