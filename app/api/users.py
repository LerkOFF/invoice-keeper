from fastapi import APIRouter, HTTPException, Response, status

from app.api.deps import AdminPrincipal, DbDep, SettingsDep
from app.models import User
from app.schemas.users import UserCreate, UserOut, UserUpdate
from app.services import users as users_service

router = APIRouter(prefix="/users", tags=["users"])

_ADMIN_ONLY = {403: {"description": "Нужна роль администратора"}}


def _get_or_404(db, user_id: int) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Пользователь не найден")
    return user


def _guard(call):
    """Превращает бизнес-ошибки сервиса в HTTP-ответы."""
    try:
        return call()
    except users_service.UserConflictError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    except users_service.ProtectedUserError as error:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(error)) from error


@router.get(
    "",
    response_model=list[UserOut],
    summary="Список пользователей (администратор)",
    description="Только обычные пользователи. Администратор из .env в списке не показывается.",
    responses=_ADMIN_ONLY,
)
def list_users(_admin: AdminPrincipal, db: DbDep) -> list[User]:
    return users_service.list_users(db)


@router.post(
    "",
    response_model=UserOut,
    status_code=status.HTTP_201_CREATED,
    summary="Создание обычного пользователя (администратор)",
    responses={**_ADMIN_ONLY, 409: {"description": "Логин занят или зарезервирован"}},
)
def create_user(payload: UserCreate, _admin: AdminPrincipal, db: DbDep, settings: SettingsDep) -> User:
    return _guard(lambda: users_service.create_user(db, settings, payload.login, payload.password))


@router.patch(
    "/{id}",
    response_model=UserOut,
    summary="Изменение пользователя (администратор)",
    description="Меняет логин и/или пароль. Роль изменить нельзя. Смена пароля завершает сессии пользователя.",
    responses={**_ADMIN_ONLY, 409: {"description": "Логин занят или зарезервирован"}},
)
def update_user(
    id: int, payload: UserUpdate, _admin: AdminPrincipal, db: DbDep, settings: SettingsDep
) -> User:
    if payload.login is None and payload.password is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Нужно передать login или password"
        )
    user = _get_or_404(db, id)
    return _guard(lambda: users_service.update_user(db, settings, user, payload.login, payload.password))


@router.delete(
    "/{id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Удаление пользователя (администратор)",
    responses=_ADMIN_ONLY,
)
def delete_user(id: int, _admin: AdminPrincipal, db: DbDep) -> Response:  # noqa: A002
    user = _get_or_404(db, id)
    _guard(lambda: users_service.delete_user(db, user))
    return Response(status_code=status.HTTP_204_NO_CONTENT)
