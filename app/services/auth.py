import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.security import hash_password, verify_password
from app.models import AuthSession, Role, User

# Хэш для выравнивания времени ответа, когда логина в базе нет
_DUMMY_HASH = hash_password("timing-equalizer")


@dataclass(frozen=True)
class Principal:
    """Кто делает запрос. У администратора из .env нет записи в базе, поэтому id пуст."""

    id: int | None
    login: str
    role: Role

    @property
    def is_admin(self) -> bool:
        return self.role == Role.ADMIN


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _admin_token_hash(settings: Settings, token: str) -> str:
    """Хэш токена администратора с ключом из его логина и пароля в .env.

    Сменили ADMIN_LOGIN или ADMIN_PASSWORD: хэш уже не сойдётся, и все прежние сессии администратора закрыты.
    """
    key = f"{settings.admin_login}\0{settings.admin_password}".encode()
    return hmac.new(key, token.encode(), hashlib.sha256).hexdigest()


def _find_session(db: Session, settings: Settings, token: str) -> AuthSession | None:
    plain, admin = _hash_token(token), _admin_token_hash(settings, token)
    for session in db.scalars(select(AuthSession).where(AuthSession.token_hash.in_((plain, admin)))):
        # сессия администратора находится только по хэшу с текущим паролем, пользователя по обычному
        if session.token_hash == (admin if session.is_admin else plain):
            return session
    return None


def _aware(value: datetime) -> datetime:
    # SQLite возвращает время без пояса, в базу мы всегда пишем UTC
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _is_admin_credentials(settings: Settings, login: str, password: str) -> bool:
    login_ok = secrets.compare_digest(login.encode(), settings.admin_login.encode())
    password_ok = secrets.compare_digest(password.encode(), settings.admin_password.encode())
    return login_ok and password_ok


def authenticate(db: Session, settings: Settings, login: str, password: str) -> Principal | None:
    """Проверяет логин и пароль. Логин администратора в базе не ищется никогда."""
    if login == settings.admin_login:
        if _is_admin_credentials(settings, login, password):
            return Principal(id=None, login=settings.admin_login, role=Role.ADMIN)
        return None

    user = db.scalar(select(User).where(User.login == login))
    if user is None:
        verify_password(_DUMMY_HASH, password)
        return None
    if not verify_password(user.password_hash, password):
        return None
    return Principal(id=user.id, login=user.login, role=Role(user.role))


def create_session(db: Session, settings: Settings, principal: Principal) -> str:
    """Создаёт серверную сессию и возвращает токен. В базе лежит только его хэш."""
    token = secrets.token_urlsafe(32)
    db.add(
        AuthSession(
            token_hash=_admin_token_hash(settings, token) if principal.is_admin else _hash_token(token),
            user_id=principal.id,
            is_admin=principal.is_admin,
            expires_at=datetime.now(UTC) + timedelta(hours=settings.session_ttl_hours),
        )
    )
    db.commit()
    return token


def get_principal(db: Session, settings: Settings, token: str) -> Principal | None:
    """Находит владельца живой сессии. Просроченную сессию удаляет."""
    session = _find_session(db, settings, token)
    if session is None:
        return None

    if _aware(session.expires_at) <= datetime.now(UTC):
        db.delete(session)
        db.commit()
        return None

    if session.is_admin:
        return Principal(id=None, login=settings.admin_login, role=Role.ADMIN)

    user = db.get(User, session.user_id) if session.user_id is not None else None
    if user is None:
        db.delete(session)
        db.commit()
        return None
    return Principal(id=user.id, login=user.login, role=Role(user.role))


def delete_session(db: Session, settings: Settings, token: str) -> None:
    session = _find_session(db, settings, token)
    if session is not None:
        db.delete(session)
        db.commit()
