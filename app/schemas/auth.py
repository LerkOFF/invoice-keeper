from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models import Role
from app.schemas.common import UtcDateTime
from app.schemas.users import Password


class LoginRequest(BaseModel):
    login: str = Field(min_length=1, max_length=64, examples=["admin"])
    password: str = Field(min_length=1, max_length=256)
    otp: str | None = Field(
        default=None,
        max_length=16,
        description="Код из приложения-аутентификатора, если у администратора включён двухфакторный вход",
        examples=["123456"],
    )


class CurrentUser(BaseModel):
    id: int | None = Field(description="Пусто у администратора из .env")
    login: str
    role: Role
    two_factor: bool = Field(default=False, description="Вход защищён вторым фактором (TOTP)")
    via_token: bool = Field(default=False, description="Запрос пришёл с API-токеном, а не по сессии")


class LoginResponse(BaseModel):
    token: str = Field(description="Токен сессии: заголовок Authorization: Bearer <token> или cookie")
    token_type: str = "bearer"
    user: CurrentUser


class LogoutResponse(BaseModel):
    ok: bool = True


class PasswordChange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    current_password: str = Field(min_length=1, max_length=256)
    new_password: Password


class PasswordChangeOut(BaseModel):
    ended_sessions: int = Field(description="Сколько других сессий закрыто")


class SessionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    current: bool = Field(description="Сессия, с которой пришёл этот запрос")
    created_at: UtcDateTime
    expires_at: UtcDateTime
    last_seen_at: UtcDateTime | None
    ip: str | None
    user_agent: str | None


class SessionsEnded(BaseModel):
    ended: int


Scope = Literal["read", "write"]


class ApiTokenCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=64, examples=["Google Таблицы"])
    scope: Scope = Field(description="read: только GET, write: чтение и изменения с правами владельца")
    expires_in_days: int | None = Field(default=None, ge=1, le=3650, description="Пусто: бессрочно, пока не отзовут")

    @field_validator("name")
    @classmethod
    def _strip(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Название не может быть пустым")
        return value


class ApiTokenOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    scope: Scope
    prefix: str = Field(description="Начало токена, чтобы узнать его в списке")
    created_at: UtcDateTime
    expires_at: UtcDateTime | None
    last_used_at: UtcDateTime | None


class ApiTokenCreated(ApiTokenOut):
    token: str = Field(description="Сам токен. Показывается один раз, сохраните его сразу")
