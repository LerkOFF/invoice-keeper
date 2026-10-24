from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.security import hash_password
from app.models import ApiToken, AuthSession, Role, User


class UserConflictError(Exception):
    """Логин занят или зарезервирован за администратором."""


class ProtectedUserError(Exception):
    """Попытка управлять учётной записью, которая не обычный пользователь."""


def _ensure_login_free(db: Session, settings: Settings, login: str, exclude_id: int | None = None) -> None:
    if login.lower() == settings.admin_login.lower():
        raise UserConflictError("Этот логин зарезервирован")
    stmt = select(User.id).where(func.lower(User.login) == login.lower())
    if exclude_id is not None:
        stmt = stmt.where(User.id != exclude_id)
    if db.scalar(stmt) is not None:
        raise UserConflictError("Пользователь с таким логином уже есть")


def ensure_manageable(user: User) -> None:
    """Через API управляются только обычные пользователи, администратор живёт в .env."""
    if user.role != Role.USER.value:
        raise ProtectedUserError("Учётная запись администратора не управляется через панель")


def list_users(db: Session) -> list[User]:
    return list(db.scalars(select(User).where(User.role == Role.USER.value).order_by(User.id)))


def create_user(db: Session, settings: Settings, login: str, password: str) -> User:
    _ensure_login_free(db, settings, login)
    user = User(login=login, password_hash=hash_password(password), role=Role.USER.value)
    db.add(user)
    db.commit()
    return user


def update_user(
    db: Session, settings: Settings, user: User, login: str | None, password: str | None
) -> User:
    ensure_manageable(user)
    if login is not None and login != user.login:
        _ensure_login_free(db, settings, login, exclude_id=user.id)
        user.login = login
    if password is not None:
        user.password_hash = hash_password(password)
        # смена пароля завершает все сессии пользователя
        db.execute(delete(AuthSession).where(AuthSession.user_id == user.id))
    db.commit()
    return user


def delete_user(db: Session, user: User) -> None:
    ensure_manageable(user)
    db.execute(delete(AuthSession).where(AuthSession.user_id == user.id))
    db.execute(delete(ApiToken).where(ApiToken.user_id == user.id))
    db.delete(user)
    db.commit()
