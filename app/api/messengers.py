from fastapi import APIRouter, HTTPException, Response, status

from app.api.deps import CurrentPrincipal, DbDep, SettingsDep
from app.schemas.messengers import LinkCodeOut, Messenger, MessengerStatusOut
from app.services import audit, links
from app.services.notify import NotifyError

router = APIRouter(prefix="/me/messengers", tags=["messengers"])


@router.get(
    "",
    response_model=list[MessengerStatusOut],
    summary="Мои привязки Telegram и MAX",
    description="Привязанному аккаунту бот присылает напоминания в личку с кнопкой «Оплачено».",
)
def my_messengers(principal: CurrentPrincipal, db: DbDep, settings: SettingsDep) -> list[MessengerStatusOut]:
    mine = links.links_of(db, links.Owner.of(principal))
    result = []
    for messenger in links.MESSENGERS:
        link = mine.get(messenger)
        result.append(
            MessengerStatusOut(
                messenger=messenger,
                title=links.MESSENGER_TITLES[messenger],
                available=links.bot_available(settings, messenger),
                linked=link is not None,
                account=link.display_name if link else None,
                linked_at=link.linked_at if link else None,
            )
        )
    return result


@router.post(
    "/{messenger}/link",
    response_model=LinkCodeOut,
    summary="Получить ссылку для привязки",
    description=(
        "Одноразовый код на 10 минут. Откройте `url` и нажмите «Старт» (или отправьте боту `command`): "
        "бот свяжет аккаунт с текущим пользователем. Новая ссылка отменяет прежнюю."
    ),
    responses={503: {"description": "Бот этого мессенджера не настроен"}},
)
def create_link(messenger: Messenger, principal: CurrentPrincipal, db: DbDep, settings: SettingsDep) -> LinkCodeOut:
    if not links.bot_available(settings, messenger):
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Бот этого мессенджера не настроен на сервере")
    code, expires_at = links.create_code(db, links.Owner.of(principal), messenger)
    try:
        url = links.start_url(messenger, links.bot_username(settings, messenger), code)
    except NotifyError:
        url = None  # без имени бота остаётся команда /start с кодом
    return LinkCodeOut(messenger=messenger, url=url, command=f"/start {code}", expires_at=expires_at)


@router.delete(
    "/{messenger}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Отвязать аккаунт",
    responses={404: {"description": "Аккаунт не привязан"}},
)
def remove_link(messenger: Messenger, principal: CurrentPrincipal, db: DbDep, settings: SettingsDep) -> Response:
    if not links.unlink(db, settings, links.Owner.of(principal), messenger, audit.actor_of(principal)):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Аккаунт не привязан")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
