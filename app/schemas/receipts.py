from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import UtcDateTime


class ReceiptLinkCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str = Field(max_length=2000, examples=["https://bank.example/receipts/123"])
    title: str | None = Field(default=None, max_length=200, examples=["Чек из банка"])


class ReceiptOut(BaseModel):
    id: int
    occurrence_id: int
    kind: Literal["link", "file"]
    title: str | None
    url: str | None = Field(description="Адрес для ссылки")
    filename: str | None = Field(description="Имя загруженного файла")
    content_type: str | None
    size_bytes: int | None
    download_url: str | None = Field(description="Адрес скачивания файла, нужна авторизация")
    created_at: UtcDateTime
    created_by: str
    created_by_type: str
    can_delete: bool = Field(description="Может ли текущий пользователь удалить вложение: администратор или автор")
