from pydantic import BaseModel, Field

from app.models import Role


class LoginRequest(BaseModel):
    login: str = Field(min_length=1, max_length=64, examples=["admin"])
    password: str = Field(min_length=1, max_length=256)


class CurrentUser(BaseModel):
    id: int | None = Field(description="Пусто у администратора из .env")
    login: str
    role: Role


class LoginResponse(BaseModel):
    token: str = Field(description="Токен сессии: заголовок Authorization: Bearer <token> или cookie")
    token_type: str = "bearer"
    user: CurrentUser


class LogoutResponse(BaseModel):
    ok: bool = True
