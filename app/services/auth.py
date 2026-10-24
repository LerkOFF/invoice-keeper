import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.security import hash_password, verify_password
from app.models import ApiToken, AuthSession, Role, User
from app.services.totp import admin_otp

# Хэш для выравнивания времени ответа, когда логина в базе нет
_DUMMY_HASH = hash_password("timing-equalizer")

# Отметку «последняя активность» пишем не на каждый запрос, а не чаще этого
SEEN_EVERY = timedelta(minutes=5)
# API-токены отличаются от токенов сессий началом
TOKEN_PREFIX = "ik_"


@dataclass(frozen=True)
class Principal:
    """Кто делает запрос. У администратора из .env нет записи в базе, поэтому id пуст.

    session_id: запрос по сессии из входа; token_id и token_scope: по API-токену.
    """

    id: int | None
    login: str
    role: Role
    session_id: int | None = None
    token_id: int | None = None
    token_scope: str | None = None

    @property
    def is_admin(self) -> bool:
        return self.role == Role.ADMIN

    @property
    def via_token(self) -> bool:
        return self.token_id is not None


class CurrentSessionError(Exception):
    """Текущую сессию завершает выход, а не список сессий."""


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _admin_key(settings: Settings) -> bytes:
    # секрет 2FA входит в ключ только когда задан: включение 2FA закрывает прежние сессии, без него ключ прежний
    parts = [settings.admin_login, settings.admin_password]
    if settings.admin_totp_secret:
        parts.append(settings.admin_totp_secret)
    return "\0".join(parts).encode()


def _admin_token_hash(settings: Settings, token: str) -> str:
    """Хэш токена администратора с ключом из его учётных данных в .env.

    Сменили ADMIN_LOGIN, ADMIN_PASSWORD или ADMIN_TOTP_SECRET: хэш уже не сойдётся,
    и все прежние сессии и API-токены администратора перестают действовать.
    """
    return hmac.new(_admin_key(settings), token.encode(), hashlib.sha256).hexdigest()


def admin_key_tag(settings: Settings) -> str:
    """Метка текущих учётных данных администратора: по ней список отсеивает уже недействительные сессии."""
    return hmac.new(_admin_key(settings), b"key-tag", hashlib.sha256).hexdigest()[:16]


def hash_for(settings: Settings, token: str, is_admin: bool) -> str:
    return _admin_token_hash(settings, token) if is_admin else _hash_token(token)


def _find(db: Session, settings: Settings, model: type[AuthSession] | type[ApiToken], token: str):
    plain, admin = _hash_token(token), _admin_token_hash(settings, token)
    for row in db.scalars(select(model).where(model.token_hash.in_((plain, admin)))):
        # администратор находится только по хэшу с текущими учётными данными, пользователь по обычному
        if row.token_hash == (admin if row.is_admin else plain):
            return row
    return None


def _aware(value: datetime) -> datetime:
    # SQLite возвращает время без пояса, в базу мы всегда пишем UTC
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def owned_by(model, principal: Principal):  # noqa: ANN001, ANN201
    """Условие «запись принадлежит этому входу»: администратору из .env или пользователю по id."""
    return model.is_admin.is_(True) if principal.is_admin else model.user_id == principal.id


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


def needs_otp(settings: Settings, principal: Principal) -> bool:
    """Второй фактор нужен администратору, когда в .env задан ADMIN_TOTP_SECRET."""
    return principal.is_admin and bool(settings.admin_totp_secret)


def check_otp(settings: Settings, code: str) -> bool:
    """Код из приложения-аутентификатора. Каждый код действует один раз."""
    return admin_otp.verify(settings.admin_totp_secret, code)


def create_session(
    db: Session, settings: Settings, principal: Principal, ip: str | None = None, user_agent: str | None = None
) -> str:
    """Создаёт серверную сессию и возвращает токен. В базе лежит только его хэш."""
    token = secrets.token_urlsafe(32)
    now = datetime.now(UTC)
    db.add(
        AuthSession(
            token_hash=hash_for(settings, token, principal.is_admin),
            user_id=principal.id,
            is_admin=principal.is_admin,
            key_tag=admin_key_tag(settings) if principal.is_admin else None,
            expires_at=now + timedelta(hours=settings.session_ttl_hours),
            ip=ip,
            user_agent=(user_agent or "")[:256] or None,
            last_seen_at=now,
        )
    )
    db.commit()
    return token


def _owner(db: Session, settings: Settings, row: AuthSession | ApiToken) -> Principal | None:
    if row.is_admin:
        return Principal(id=None, login=settings.admin_login, role=Role.ADMIN)
    user = db.get(User, row.user_id) if row.user_id is not None else None
    return Principal(id=user.id, login=user.login, role=Role(user.role)) if user else None


def _touch(row: AuthSession | ApiToken, field: str, settings: Settings, now: datetime) -> bool:
    changed = False
    seen = getattr(row, field)
    if seen is None or now - _aware(seen) >= SEEN_EVERY:
        setattr(row, field, now)
        changed = True
    if row.is_admin and row.key_tag is None:
        # запись появилась до меток: найдена по текущему ключу, значит действительна
        row.key_tag = admin_key_tag(settings)
        changed = True
    return changed


def _session_principal(db: Session, settings: Settings, token: str) -> Principal | None:
    session = _find(db, settings, AuthSession, token)
    if session is None:
        return None

    now = datetime.now(UTC)
    owner = _owner(db, settings, session) if _aware(session.expires_at) > now else None
    if owner is None:
        # просроченная сессия или сессия удалённого пользователя
        db.delete(session)
        db.commit()
        return None
    if _touch(session, "last_seen_at", settings, now):
        db.commit()
    return Principal(owner.id, owner.login, owner.role, session_id=session.id)


def _token_principal(db: Session, settings: Settings, token: str) -> Principal | None:
    row = _find(db, settings, ApiToken, token)
    if row is None:
        return None

    now = datetime.now(UTC)
    if row.expires_at is not None and _aware(row.expires_at) <= now:
        return None  # истёкший токен остаётся в списке владельца, пока тот его не отзовёт
    owner = _owner(db, settings, row)
    if owner is None:
        return None
    if _touch(row, "last_used_at", settings, now):
        db.commit()
    return Principal(owner.id, owner.login, owner.role, token_id=row.id, token_scope=row.scope)


def get_principal(db: Session, settings: Settings, token: str) -> Principal | None:
    """Находит владельца живой сессии или API-токена. Просроченную сессию удаляет."""
    if token.startswith(TOKEN_PREFIX):
        return _token_principal(db, settings, token)
    return _session_principal(db, settings, token)


def delete_session(db: Session, settings: Settings, token: str) -> None:
    session = _find(db, settings, AuthSession, token)
    if session is not None:
        db.delete(session)
        db.commit()


# ---------- «Мои сессии» ----------


def drop_stale(db: Session, settings: Settings, model, principal: Principal) -> None:  # noqa: ANN001
    """Удаляет записи администратора, выданные под прежние учётные данные: они уже не действуют."""
    if principal.is_admin:
        db.execute(delete(model).where(model.is_admin.is_(True), model.key_tag.is_not(None), model.key_tag != admin_key_tag(settings)))


def list_sessions(db: Session, settings: Settings, principal: Principal) -> list[AuthSession]:
    now = datetime.now(UTC)
    drop_stale(db, settings, AuthSession, principal)
    db.execute(delete(AuthSession).where(owned_by(AuthSession, principal), AuthSession.expires_at <= now))
    db.commit()
    stmt = select(AuthSession).where(owned_by(AuthSession, principal))
    if principal.is_admin:
        stmt = stmt.where(AuthSession.key_tag == admin_key_tag(settings))
    sessions = list(db.scalars(stmt))
    # текущая первой, остальные по последней активности
    return sorted(sessions, key=lambda s: (s.id != principal.session_id, -_aware(s.last_seen_at or s.created_at).timestamp()))


def end_session(db: Session, principal: Principal, session_id: int) -> bool:
    if session_id == principal.session_id:
        raise CurrentSessionError("Это текущая сессия: чтобы её завершить, выйдите из панели")
    session = db.scalar(select(AuthSession).where(AuthSession.id == session_id, owned_by(AuthSession, principal)))
    if session is None:
        return False
    db.delete(session)
    return True


def end_other_sessions(db: Session, principal: Principal) -> int:
    stmt = delete(AuthSession).where(owned_by(AuthSession, principal))
    if principal.session_id is not None:
        stmt = stmt.where(AuthSession.id != principal.session_id)
    return db.execute(stmt).rowcount or 0


def change_password(db: Session, principal: Principal, new_password: str) -> int:
    """Новый пароль пользователя. Остальные его сессии закрываются, текущая остаётся. Возвращает их число."""
    user = db.get(User, principal.id)
    user.password_hash = hash_password(new_password)
    return end_other_sessions(db, principal)
