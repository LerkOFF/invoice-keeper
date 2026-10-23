from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.models import Role
from app.schemas.common import UtcDateTime

Login = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=3, max_length=64, pattern=r"^[A-Za-z0-9._@-]+$"),
]
Password = Annotated[str, Field(min_length=8, max_length=128)]


class UserCreate(BaseModel):
    """Создаётся только обычный пользователь: поля роли нет, лишние поля запрещены."""

    model_config = ConfigDict(extra="forbid")

    login: Login = Field(examples=["ivan"])
    password: Password


class UserUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    login: Login | None = None
    password: Password | None = Field(default=None, description="Новый пароль, прежние сессии пользователя завершаются")


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    login: str
    role: Role
    created_at: UtcDateTime
