from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


def _utcnow() -> datetime:
    return datetime.now(UTC)


class MessengerLink(Base):
    """Аккаунт Telegram или MAX, привязанный к пользователю панели (или к администратору из .env).

    Один аккаунт мессенджера принадлежит одному пользователю, у пользователя по одному аккаунту на мессенджер.
    """

    __tablename__ = "messenger_links"
    __table_args__ = (UniqueConstraint("messenger", "external_user_id", name="uq_link_messenger_account"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    messenger: Mapped[str] = mapped_column(String(16))  # telegram или max
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    external_user_id: Mapped[str] = mapped_column(String(32))
    chat_id: Mapped[str] = mapped_column(String(32))  # личный чат с ботом, туда идут напоминания
    display_name: Mapped[str] = mapped_column(String(100))
    linked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class MessengerLinkCode(Base):
    """Одноразовый код привязки из ссылки на бота. В базе только хэш, живёт несколько минут."""

    __tablename__ = "messenger_link_codes"

    id: Mapped[int] = mapped_column(primary_key=True)
    code_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    messenger: Mapped[str] = mapped_column(String(16))
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
