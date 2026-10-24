from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class AuthSession(Base):
    """Серверная сессия. user_id пуст, когда вошёл администратор из .env."""

    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # Для списка «Мои сессии». Колонки добавлены позже, в старой базе их создаёт migrate()
    ip: Mapped[str | None] = mapped_column(String(45))
    user_agent: Mapped[str | None] = mapped_column(String(256))
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # У сессии администратора: метка текущих учётных данных из .env, чтобы не показывать в списке уже недействительные
    key_tag: Mapped[str | None] = mapped_column(String(16))


class AdminTwoFactor(Base):
    """Второй фактор администратора, включённый из панели. Одна строка с id=1.

    Действует, только когда в .env нет ADMIN_TOTP_SECRET: секрет из .env главнее.
    pending_secret: выдан для настройки, но ещё не подтверждён кодом из приложения.
    """

    __tablename__ = "admin_two_factor"

    id: Mapped[int] = mapped_column(primary_key=True)
    secret: Mapped[str | None] = mapped_column(String(64))
    pending_secret: Mapped[str | None] = mapped_column(String(64))
    enabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ApiToken(Base):
    """Токен для интеграций вместо сессии. В базе только хэш, сам токен показывается один раз при создании."""

    __tablename__ = "api_tokens"

    id: Mapped[int] = mapped_column(primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    key_tag: Mapped[str | None] = mapped_column(String(16))
    name: Mapped[str] = mapped_column(String(64))
    scope: Mapped[str] = mapped_column(String(8))  # read или write
    prefix: Mapped[str] = mapped_column(String(16))  # начало токена, чтобы узнать его в списке
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
