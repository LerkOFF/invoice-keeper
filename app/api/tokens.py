from fastapi import APIRouter, HTTPException, Request, Response, status

from app.api.deps import DbDep, SessionPrincipal, SettingsDep, client_ip
from app.schemas.auth import ApiTokenCreate, ApiTokenCreated, ApiTokenOut
from app.services import api_tokens, audit

router = APIRouter(prefix="/me/tokens", tags=["tokens"])


@router.get(
    "",
    response_model=list[ApiTokenOut],
    summary="Мои API-токены",
    description="Сами токены не показываются, только их начало. Управлять токенами можно только после входа по паролю.",
    responses={403: {"description": "Запрос с API-токеном"}},
)
def my_tokens(db: DbDep, settings: SettingsDep, principal: SessionPrincipal) -> list[ApiTokenOut]:
    return [ApiTokenOut.model_validate(row) for row in api_tokens.list_tokens(db, settings, principal)]


@router.post(
    "",
    response_model=ApiTokenCreated,
    status_code=status.HTTP_201_CREATED,
    summary="Создать API-токен",
    description=(
        "Токен для скриптов и интеграций: заголовок `Authorization: Bearer ik_...`. Права те же, что у владельца, "
        "`read` дополнительно ограничивает до GET. Токен показывается в ответе один раз."
    ),
    responses={403: {"description": "Запрос с API-токеном"}, 409: {"description": "Слишком много токенов"}},
)
def create_token(
    payload: ApiTokenCreate, request: Request, db: DbDep, settings: SettingsDep, principal: SessionPrincipal
) -> ApiTokenCreated:
    try:
        row, token = api_tokens.create_token(db, settings, principal, payload.name, payload.scope, payload.expires_in_days)
    except api_tokens.TokenLimitError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    details = {"name": row.name, "scope": row.scope}
    audit.record(db, "token.create", audit.actor_of(principal), "token", row.id, details, ip=client_ip(request))
    db.commit()
    return ApiTokenCreated(**ApiTokenOut.model_validate(row).model_dump(), token=token)


@router.delete(
    "/{id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Отозвать API-токен",
    responses={403: {"description": "Запрос с API-токеном"}, 404: {"description": "Токен не найден"}},
)
def revoke_token(id: int, request: Request, db: DbDep, principal: SessionPrincipal) -> Response:
    row = api_tokens.revoke_token(db, principal, id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Токен не найден")
    audit.record(db, "token.revoke", audit.actor_of(principal), "token", id, {"name": row.name}, ip=client_ip(request))
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
