import math
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from app.api.deps import (
    SESSION_COOKIE,
    client_ip,
    CurrentPrincipal,
    DbDep,
    SessionPrincipal,
    SettingsDep,
    bearer_scheme,
    extract_token,
)
from app.core.config import Settings
from app.schemas.auth import (
    CurrentUser,
    LoginRequest,
    LoginResponse,
    LogoutResponse,
    PasswordChange,
    PasswordChangeOut,
    SessionOut,
    SessionsEnded,
)
from app.services import audit
from app.services import auth as auth_service
from app.services.login_guard import login_guard

router = APIRouter(prefix="/auth", tags=["auth"])

# Заголовок ответа 401: пароль верный, нужен ещё код из приложения-аутентификатора
OTP_HEADER = "X-OTP-Required"


def _too_many(wait: int) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail=f"Слишком много неудачных попыток входа. Попробуйте через {math.ceil(wait / 60)} мин.",
        headers={"Retry-After": str(wait)},
    )


def _to_user(principal: auth_service.Principal, settings: Settings) -> CurrentUser:
    return CurrentUser(
        id=principal.id,
        login=principal.login,
        role=principal.role,
        two_factor=auth_service.needs_otp(settings, principal),
        via_token=principal.via_token,
    )


def _failed(db: Session, settings: Settings, ip: str | None, login: str, action: str, actor: audit.Actor) -> int:
    """Неудачная попытка: в счётчик защиты от перебора и в журнал. Возвращает, на сколько секунд закрыт вход."""
    window = settings.login_lock_minutes * 60
    login_guard.failure(ip, login, window)
    audit.record(db, action, actor, ip=ip)
    wait = login_guard.retry_after(ip, login, settings.login_max_failures, window)
    if wait:
        audit.record(db, "auth.login_locked", actor, ip=ip, details={"minutes": math.ceil(wait / 60)})
    db.commit()
    return wait


@router.post(
    "/login",
    response_model=LoginResponse,
    summary="Вход по логину и паролю",
    description=(
        "Если у администратора включён двухфакторный вход (`ADMIN_TOTP_SECRET`), без поля `otp` ответ 401 "
        f"с заголовком `{OTP_HEADER}: true`: повторите запрос с кодом из приложения-аутентификатора."
    ),
    responses={
        401: {"description": f"Неверный логин, пароль или код; заголовок {OTP_HEADER}, если нужен код"},
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
        # пароль в журнал не попадает, только попытка входа с таким логином
        actor = audit.Actor("anonymous", payload.login[:64])
        if wait := _failed(db, settings, ip, payload.login, "auth.login_failed", actor):
            raise _too_many(wait)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Неверный логин или пароль")

    if auth_service.needs_otp(settings, principal):
        otp_required = {OTP_HEADER: "true"}
        if not payload.otp:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Введите код из приложения-аутентификатора",
                headers=otp_required,
            )
        if not auth_service.check_otp(settings, payload.otp):
            if wait := _failed(db, settings, ip, payload.login, "auth.otp_failed", audit.actor_of(principal)):
                raise _too_many(wait)
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Неверный или уже использованный код", headers=otp_required)

    login_guard.success(ip, payload.login)

    token = auth_service.create_session(db, settings, principal, ip, request.headers.get("user-agent"))
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
    return LoginResponse(token=token, user=_to_user(principal, settings))


@router.get(
    "/me",
    response_model=CurrentUser,
    summary="Текущий пользователь",
    responses={401: {"description": "Нет авторизации"}},
)
def me(principal: CurrentPrincipal, settings: SettingsDep) -> CurrentUser:
    return _to_user(principal, settings)


@router.post(
    "/logout",
    response_model=LogoutResponse,
    summary="Завершение текущей сессии",
    responses={401: {"description": "Нет авторизации"}, 403: {"description": "Запрос с API-токеном: его отзывают в /me/tokens"}},
)
def logout(
    request: Request,
    response: Response,
    db: DbDep,
    settings: SettingsDep,
    principal: SessionPrincipal,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> LogoutResponse:
    token = extract_token(request, credentials)
    if token:
        auth_service.delete_session(db, settings, token)
    audit.record(db, "auth.logout", audit.actor_of(principal), ip=client_ip(request))
    db.commit()
    response.delete_cookie(SESSION_COOKIE)
    return LogoutResponse()


@router.post(
    "/password",
    response_model=PasswordChangeOut,
    summary="Сменить свой пароль",
    description=(
        "Нужен текущий пароль. Остальные сессии закрываются, текущая остаётся. Неверный текущий пароль "
        "считается неудачной попыткой входа. Пароль администратора задаётся в `.env`, здесь не меняется."
    ),
    responses={
        400: {"description": "Неверный текущий пароль или новый совпадает с ним"},
        403: {"description": "Администратор из .env или запрос с API-токеном"},
        429: {"description": "Слишком много неудачных попыток"},
    },
)
def change_password(
    payload: PasswordChange, request: Request, db: DbDep, settings: SettingsDep, principal: SessionPrincipal
) -> PasswordChangeOut:
    if principal.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Пароль администратора задаётся в .env (ADMIN_PASSWORD)")
    ip = client_ip(request)
    window = settings.login_lock_minutes * 60
    if wait := login_guard.retry_after(ip, principal.login, settings.login_max_failures, window):
        raise _too_many(wait)

    if auth_service.authenticate(db, settings, principal.login, payload.current_password) is None:
        if wait := _failed(db, settings, ip, principal.login, "auth.password_failed", audit.actor_of(principal)):
            raise _too_many(wait)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Неверный текущий пароль")
    if payload.new_password == payload.current_password:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Новый пароль совпадает с текущим")

    login_guard.success(ip, principal.login)
    ended = auth_service.change_password(db, principal, payload.new_password)
    audit.record(db, "auth.password_changed", audit.actor_of(principal), "user", principal.id, {"ended_sessions": ended}, ip=ip)
    db.commit()
    return PasswordChangeOut(ended_sessions=ended)


@router.get(
    "/sessions",
    response_model=list[SessionOut],
    summary="Мои сессии",
    description="Все входы в эту учётную запись, которые ещё действуют. Текущая сессия первой.",
    responses={403: {"description": "Запрос с API-токеном"}},
)
def my_sessions(db: DbDep, settings: SettingsDep, principal: SessionPrincipal) -> list[SessionOut]:
    return [
        SessionOut(
            id=s.id,
            current=s.id == principal.session_id,
            created_at=s.created_at,
            expires_at=s.expires_at,
            last_seen_at=s.last_seen_at,
            ip=s.ip,
            user_agent=s.user_agent,
        )
        for s in auth_service.list_sessions(db, settings, principal)
    ]


@router.post(
    "/sessions/end-others",
    response_model=SessionsEnded,
    summary="Завершить все сессии, кроме текущей",
    responses={403: {"description": "Запрос с API-токеном"}},
)
def end_other_sessions(request: Request, db: DbDep, principal: SessionPrincipal) -> SessionsEnded:
    ended = auth_service.end_other_sessions(db, principal)
    audit.record(db, "auth.sessions_ended", audit.actor_of(principal), details={"count": ended}, ip=client_ip(request))
    db.commit()
    return SessionsEnded(ended=ended)


@router.delete(
    "/sessions/{id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Завершить сессию",
    description="Свою сессию на другом устройстве. Текущую завершает `POST /auth/logout`.",
    responses={
        400: {"description": "Это текущая сессия"},
        403: {"description": "Запрос с API-токеном"},
        404: {"description": "Сессия не найдена"},
    },
)
def end_session(id: int, request: Request, db: DbDep, principal: SessionPrincipal) -> Response:
    try:
        found = auth_service.end_session(db, principal, id)
    except auth_service.CurrentSessionError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    if not found:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Сессия не найдена")
    audit.record(db, "auth.session_ended", audit.actor_of(principal), "session", id, ip=client_ip(request))
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
