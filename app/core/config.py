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

    # MAX: то же, что Telegram. Токен бота из «MAX для бизнеса», id группового чата (или диалога с ботом)
    max_bot_token: str = ""
    max_chat_id: str = ""
    max_api_base: str = "https://platform-api2.max.ru"
    max_buttons_enabled: bool = True
    max_allowed_user_ids: str = ""
    max_poll_timeout: int = 8

    # Email-оповещения через SMTP: включаются, когда заданы хост, отправитель и получатели
    smtp_host: str = ""
    smtp_port: int = 465
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    smtp_to: str = ""  # адреса через запятую
    smtp_security: str = "ssl"  # ssl (порт 465), starttls (587) или none
    # Адрес панели для ссылки в письме, например https://keeper.example.com
    public_url: str = ""

    # Webhook: напоминания и события на указанный адрес, подпись HMAC-SHA256 при заданном секрете
    webhook_url: str = ""
    webhook_secret: str = ""
    # События журнала для отправки: точные имена или группы с точкой (по умолчанию без входов и напоминаний)
    webhook_events: str = "payment.,occurrence.,receipt.,user."

    # Чеки: куда класть файлы (по умолчанию рядом с базой, в volume) и лимиты
    receipts_dir: str = ""
    receipt_max_mb: int = 5
    receipts_per_period: int = 10

    app_timezone: str = "Europe/Moscow"
    reminder_days: int = 3
    # Повторное напоминание на следующий день после срока, если период так и не оплатили
    overdue_reminders: bool = True
    scheduler_enabled: bool = True
    scheduler_interval_seconds: float = 60
    session_ttl_hours: int = 12
    # Защита входа: после стольких неудачных попыток логина с одного адреса вход закрывается на login_lock_minutes
    login_max_failures: int = 5
    login_lock_minutes: int = 15
    cookie_secure: bool = False
    database_url: str = "sqlite:///./data/invoice_keeper.db"

    seed_demo_data: bool = True
    seed_user_login: str = "user"
    seed_user_password: str = "user-pass-123"

    @property
    def smtp_recipients(self) -> list[str]:
        return [a.strip() for a in self.smtp_to.replace(";", ",").split(",") if a.strip()]

    @property
    def webhook_event_filters(self) -> list[str]:
        return [e.strip() for e in self.webhook_events.split(",") if e.strip()]

    @property
    def allowed_telegram_ids(self) -> set[int]:
        return _ids(self.telegram_allowed_user_ids)

    @property
    def allowed_max_ids(self) -> set[int]:
        return _ids(self.max_allowed_user_ids)


def _ids(raw: str) -> set[int]:
    return {int(part) for part in raw.replace(";", ",").split(",") if part.strip()}


@lru_cache
def get_settings() -> Settings:
    return Settings()
