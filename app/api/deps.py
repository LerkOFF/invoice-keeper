from datetime import date
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.clock import today as today_in_tz
from app.core.config import Settings, get_settings
from app.core.db import get_db
from app.services.api_tokens import READ_METHODS
from app.services.auth import Principal, get_principal
from app.services.notify import Notifier
from app.services.telegram import build_notifiers

SESSION_COOKIE = "session"

# auto_error=False: токен может прийти и cookie панели, а не только заголовком
bearer_scheme = HTTPBearer(auto_error=False, description="Токен из POST /auth/login или API-токен из POST /me/tokens")

DbDep = Annotated[Session, Depends(get_db)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


def current_date() -> date:
    """«Сегодня» в часовом поясе приложения. Зависимость, чтобы тесты могли подменить дату."""
    return today_in_tz()


TodayDep = Annotated[date, Depends(current_date)]


def get_notifiers(settings: SettingsDep) -> list[Notifier]:
    """Каналы напоминаний. В тестах подменяются заглушками через dependency_overrides."""
    return build_notifiers(settings)


NotifiersDep = Annotated[list[Notifier], Depends(get_notifiers)]


def client_ip(request: Request) -> str | None:
    """Адрес клиента для журнала. За прокси это адрес прокси: заголовкам X-Forwarded-For не верим."""
    return request.client.host if request.client else None


def extract_token(request: Request, credentials: HTTPAuthorizationCredentials | None) -> str | None:
    if credentials is not None and credentials.credentials:
        return credentials.credentials
    return request.cookies.get(SESSION_COOKIE) or None


def get_current_principal(
    request: Request,
    db: DbDep,
    settings: SettingsDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> Principal:
    token = extract_token(request, credentials)
    principal = get_principal(db, settings, token) if token else None
    if principal is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Требуется авторизация",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if principal.token_scope == "read" and request.method not in READ_METHODS:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="API-токен только для чтения")
    return principal


CurrentPrincipal = Annotated[Principal, Depends(get_current_principal)]


def require_session(principal: CurrentPrincipal) -> Principal:
    """Пароль, сессии и токены меняются только после входа по паролю, API-токеном нельзя."""
    if principal.via_token:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Нужен вход по паролю, API-токен здесь не подходит")
    return principal


SessionPrincipal = Annotated[Principal, Depends(require_session)]


def require_admin(principal: CurrentPrincipal) -> Principal:
    if not principal.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Только для администратора")
    return principal


AdminPrincipal = Annotated[Principal, Depends(require_admin)]
