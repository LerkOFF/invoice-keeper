from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.common import UtcDateTime

Messenger = Literal["telegram", "max"]


class MessengerStatusOut(BaseModel):
    messenger: Messenger
    title: str
    available: bool = Field(description="Бот этого мессенджера настроен на сервере")
    linked: bool
    account: str | None = Field(description="Имя аккаунта в мессенджере, например @ivan")
    linked_at: UtcDateTime | None = None


class LinkCodeOut(BaseModel):
    messenger: Messenger
    url: str | None = Field(description="Ссылка на бота с кодом: открыть и нажать «Старт»")
    command: str = Field(description="Запасной путь: отправить это сообщение боту в личку")
    expires_at: UtcDateTime
