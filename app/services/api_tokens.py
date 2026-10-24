"""API-токены для интеграций: скрипты, таблицы, боты. Работают вместо сессии в заголовке Authorization: Bearer.

Токен только для чтения разрешает GET, токен на запись то же, что и вход по паролю, с правами владельца.
Пароль, сессии и сами токены токеном не меняются: для этого нужен вход по паролю.
"""
import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models import ApiToken
from app.services.auth import TOKEN_PREFIX, Principal, drop_stale, admin_key_tag, hash_for, owned_by

SCOPES = ("read", "write")
# Методы, которые разрешены токену только для чтения
READ_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
MAX_TOKENS = 20


class TokenLimitError(Exception):
    """У владельца уже максимум токенов."""


def list_tokens(db: Session, settings: Settings, principal: Principal) -> list[ApiToken]:
    drop_stale(db, settings, ApiToken, principal)
    db.commit()
    stmt = select(ApiToken).where(owned_by(ApiToken, principal))
    if principal.is_admin:
        stmt = stmt.where(ApiToken.key_tag == admin_key_tag(settings))
    return list(db.scalars(stmt.order_by(ApiToken.id.desc())))


def create_token(
    db: Session, settings: Settings, principal: Principal, name: str, scope: str, expires_in_days: int | None
) -> tuple[ApiToken, str]:
    """Создаёт токен и возвращает запись и сам токен. Токен больше нигде не хранится и не показывается."""
    drop_stale(db, settings, ApiToken, principal)
    count = db.scalar(select(func.count()).select_from(ApiToken).where(owned_by(ApiToken, principal)))
    if count >= MAX_TOKENS:
        raise TokenLimitError(f"Не больше {MAX_TOKENS} токенов: отзовите ненужные")

    token = TOKEN_PREFIX + secrets.token_urlsafe(32)
    row = ApiToken(
        token_hash=hash_for(settings, token, principal.is_admin),
        user_id=principal.id,
        is_admin=principal.is_admin,
        key_tag=admin_key_tag(settings) if principal.is_admin else None,
        name=name,
        scope=scope,
        prefix=token[:10],
        created_at=datetime.now(UTC),
        expires_at=datetime.now(UTC) + timedelta(days=expires_in_days) if expires_in_days else None,
    )
    db.add(row)
    db.flush()
    return row, token


def revoke_token(db: Session, principal: Principal, token_id: int) -> ApiToken | None:
    row = db.scalar(select(ApiToken).where(ApiToken.id == token_id, owned_by(ApiToken, principal)))
    if row is not None:
        db.delete(row)
    return row
