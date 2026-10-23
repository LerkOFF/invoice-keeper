from pydantic import BaseModel, Field


class ContactOut(BaseModel):
    label: str = Field(examples=["@joulerkOFF"])
    url: str = Field(examples=["https://t.me/joulerkOFF"])


class HelpContactsOut(BaseModel):
    telegram: ContactOut | None = Field(description="Telegram для вопросов, SUPPORT_TELEGRAM")
    email: ContactOut | None = Field(description="Почта для вопросов, SUPPORT_EMAIL")
    url: ContactOut | None = Field(description="Ссылка, например на репозиторий или базу знаний, SUPPORT_URL")


class HelpOut(BaseModel):
    """Всё, что странице «Помощь» нужно знать о настройках сервера."""

    contacts: HelpContactsOut
    bots: dict[str, ContactOut] = Field(description="Боты напоминаний, которые настроены на сервере: telegram, max")
    channels: list[str] = Field(description="Общие каналы напоминаний: telegram, max, email, webhook")
    reminder_days: int = Field(description="За сколько дней до срока приходит напоминание")
    overdue_reminders: bool = Field(description="Приходит ли повторное напоминание на следующий день после срока")
    timezone: str = Field(description="Часовой пояс, по которому считается «сегодня»")
