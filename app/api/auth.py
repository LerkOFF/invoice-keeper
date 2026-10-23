import math
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.security import HTTPAuthorizationCredentials

from app.api.deps import (
    SESSION_COOKIE,
    client_ip,
    CurrentPrincipal,
    DbDep,
    SettingsDep,
    bearer_scheme,
    extract_token,
)
from app.schemas.auth import CurrentUser, LoginRequest, LoginResponse, LogoutResponse
from app.services import audit
from app.services import auth as auth_service
from app.services.login_guard import login_guard

router = APIRouter(prefix="/auth", tags=["auth"])


def _too_many(wait: int) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail=f"Слишком много неудачных попыток входа. Попробуйте через {math.ceil(wait / 60)} мин.",
        headers={"Retry-After": str(wait)},
    )


def _to_user(principal: auth_service.Principal) -> CurrentUser:
    return CurrentUser(id=principal.id, login=principal.login, role=principal.role)


@router.post(
    "/login",
    response_model=LoginResponse,
    summary="Вход по логину и паролю",
    responses={
        401: {"description": "Неверный логин или пароль"},
        429: {"description": "Слишком много неудачных попыток: вход временно закрыт, заголовок Retry-After"},
    },
)
def login(
    payload: LoginRequest, request: Request, response: Response, db: DbDep, settings: SettingsDep
) -> LoginResponse:
    ip = client_ip(request)
    window = settings.login_lock_minutes * 60
    if wait := login_guard.retry_after(ip, payload.login, settings.login_max_failures, window):
        raise _too_many(wait)

    principal = auth_service.authenticate(db, settings, payload.login, payload.password)
    if principal is None:
        login_guard.failure(ip, payload.login, window)
        actor = audit.Actor("anonymous", payload.login[:64])
        # пароль в журнал не попадает, только попытка входа с таким логином
        audit.record(db, "auth.login_failed", actor, ip=ip)
        wait = login_guard.retry_after(ip, payload.login, settings.login_max_failures, window)
        if wait:
            audit.record(db, "auth.login_locked", actor, ip=ip, details={"minutes": math.ceil(wait / 60)})
        db.commit()
        if wait:
            raise _too_many(wait)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Неверный логин или пароль")

    login_guard.success(ip, payload.login)

    token = auth_service.create_session(db, settings, principal)
    audit.record(db, "auth.login", audit.actor_of(principal), ip=ip)
    db.commit()
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=settings.session_ttl_hours * 3600,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
    )
    return LoginResponse(token=token, user=_to_user(principal))


@router.get(
    "/me",
    response_model=CurrentUser,
    summary="Текущий пользователь",
    responses={401: {"description": "Нет авторизации"}},
)
def me(principal: CurrentPrincipal) -> CurrentUser:
    return _to_user(principal)


@router.post(
    "/logout",
    response_model=LogoutResponse,
    summary="Завершение текущей сессии",
    responses={401: {"description": "Нет авторизации"}},
)
def logout(
    request: Request,
    response: Response,
    db: DbDep,
    principal: CurrentPrincipal,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> LogoutResponse:
    token = extract_token(request, credentials)
    if token:
        auth_service.delete_session(db, token)
    audit.record(db, "auth.logout", audit.actor_of(principal), ip=client_ip(request))
    db.commit()
    response.delete_cookie(SESSION_COOKIE)
    return LogoutResponse()
