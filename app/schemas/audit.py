from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import UtcDateTime


class AuditEntryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    at: UtcDateTime
    actor_type: str = Field(description="admin, user, telegram, system или anonymous")
    actor: str = Field(description="Логин, @username в Telegram или «планировщик»")
    action: str = Field(examples=["occurrence.paid"])
    target_type: str | None = None
    target_id: int | None = None
    details: dict[str, Any] | None = None
    ip: str | None = None
