from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.security import HTTPAuthorizationCredentials

from app.api.deps import (
    SESSION_COOKIE,
    CurrentPrincipal,
    DbDep,
    SettingsDep,
    bearer_scheme,
    extract_token,
)
from app.schemas.auth import CurrentUser, LoginRequest, LoginResponse, LogoutResponse
from app.services import auth as auth_service

router = APIRouter(prefix="/auth", tags=["auth"])


def _to_user(principal: auth_service.Principal) -> CurrentUser:
    return CurrentUser(id=principal.id, login=principal.login, role=principal.role)


@router.post(
    "/login",
    response_model=LoginResponse,
    summary="Вход по логину и паролю",
    responses={401: {"description": "Неверный логин или пароль"}},
)
def login(payload: LoginRequest, response: Response, db: DbDep, settings: SettingsDep) -> LoginResponse:
    principal = auth_service.authenticate(db, settings, payload.login, payload.password)
    if principal is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Неверный логин или пароль")

    token = auth_service.create_session(db, settings, principal)
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
    _principal: CurrentPrincipal,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> LogoutResponse:
    token = extract_token(request, credentials)
    if token:
        auth_service.delete_session(db, token)
    response.delete_cookie(SESSION_COOKIE)
    return LogoutResponse()
