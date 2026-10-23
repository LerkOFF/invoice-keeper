from datetime import date
from typing import Annotated

from fastapi import APIRouter, Query

from app.api.deps import AdminPrincipal, DbDep
from app.models import AuditEntry
from app.schemas.audit import AuditEntryOut
from app.services import audit as audit_service

router = APIRouter(prefix="/audit-log", tags=["audit"])


@router.get(
    "",
    response_model=list[AuditEntryOut],
    summary="Журнал авторизации и действий (администратор)",
    description=(
        "Новые записи первыми. Фильтр `action`: точное имя (`occurrence.paid`) или группа с точкой на конце "
        "(`auth.`, `payment.`, `occurrence.`, `user.`, `receipt.`, `reminder.`). Пароли в журнал не попадают."
    ),
    responses={403: {"description": "Нужна роль администратора"}},
)
def list_audit_log(
    _admin: AdminPrincipal,
    db: DbDep,
    action: Annotated[str | None, Query(max_length=48)] = None,
    actor: Annotated[str | None, Query(max_length=100, description="Точное имя: логин или @username")] = None,
    since: date | None = None,
    until: date | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[AuditEntry]:
    return audit_service.list_entries(
        db, action=action, actor=actor, since=since, until=until, limit=limit, offset=offset
    )
