from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, UTC
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AuditEntry, OccurrenceStatus, PaymentOccurrence
from app.services.auth import Principal


@dataclass(frozen=True)
class Actor:
    type: str  # admin, user, telegram, max, system, anonymous
    name: str


SYSTEM = Actor("system", "планировщик")

ACTION_LABELS = {
    "auth.login": "Вход",
    "auth.login_failed": "Неудачный вход",
    "auth.logout": "Выход",
    "payment.create": "Платёж добавлен",
    "payment.delete": "Платёж прекращён",
    "occurrence.paid": "Оплата отмечена",
    "occurrence.unpaid": "Оплата отменена",
    "occurrence.paid_at_changed": "Дата оплаты исправлена",
    "user.create": "Пользователь создан",
    "user.update": "Пользователь изменён",
    "user.delete": "Пользователь удалён",
    "receipt.add": "Чек или ссылка добавлены",
    "receipt.delete": "Чек или ссылка удалены",
    "reminder.sent": "Напоминание отправлено",
}


def actor_of(principal: Principal) -> Actor:
    return Actor(principal.role.value, principal.login)


def telegram_actor(user: dict[str, Any]) -> Actor:
    if user.get("username"):
        name = f"@{user['username']}"
    else:
        name = " ".join(p for p in (user.get("first_name"), user.get("last_name")) if p) or f"id {user.get('id')}"
    return Actor("telegram", name)


def max_actor(user: dict[str, Any]) -> Actor:
    if user.get("username"):
        name = f"@{user['username']}"
    else:
        name = " ".join(p for p in (user.get("first_name"), user.get("last_name")) if p) or f"id {user.get('user_id')}"
    return Actor("max", name)


def record(
    db: Session,
    action: str,
    actor: Actor,
    target_type: str | None = None,
    target_id: int | None = None,
    details: dict[str, Any] | None = None,
    ip: str | None = None,
) -> AuditEntry:
    """Добавляет запись в сессию. Коммит остаётся за вызывающим, чтобы действие и след о нём сохранялись вместе."""
    entry = AuditEntry(
        actor_type=actor.type,
        actor=actor.name[:100],
        action=action,
        target_type=target_type,
        target_id=target_id,
        details=details,
        ip=ip,
    )
    db.add(entry)
    # Событие уйдёт на webhook после успешного коммита сессии (см. services/webhook.py)
    subject = (details or {}).get("name") or (details or {}).get("login") or ""
    label = ACTION_LABELS.get(action, action)
    db.info.setdefault("audit_events", []).append(
        {
            "event": action,
            "text": f"{label}: {subject}" if subject else label,
            "at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "actor": {"type": actor.type, "name": actor.name},
            "target": {"type": target_type, "id": target_id},
            "details": details,
        }
    )
    return entry


def record_occurrence_change(
    db: Session,
    occurrence: PaymentOccurrence,
    before_status: str,
    before_paid_at: date | None,
    actor: Actor,
    source: str,
) -> AuditEntry | None:
    """Пишет, что именно изменилось в периоде: оплата, отмена или правка даты. Нет изменений, нет записи."""
    paid, unpaid = OccurrenceStatus.PAID.value, OccurrenceStatus.UNPAID.value
    if before_status == unpaid and occurrence.status == paid:
        action = "occurrence.paid"
    elif before_status == paid and occurrence.status == unpaid:
        action = "occurrence.unpaid"
    elif before_status == paid and occurrence.status == paid and before_paid_at != occurrence.paid_at:
        action = "occurrence.paid_at_changed"
    else:
        return None

    details: dict[str, Any] = {
        "name": occurrence.recurring_payment.name,
        "due_date": occurrence.due_date.isoformat(),
        "paid_at": occurrence.paid_at.isoformat() if occurrence.paid_at else None,
        "source": source,
    }
    if action == "occurrence.paid_at_changed":
        details["paid_at_before"] = before_paid_at.isoformat() if before_paid_at else None
    return record(db, action, actor, "occurrence", occurrence.id, details)


def list_entries(
    db: Session,
    *,
    action: str | None,
    actor: str | None,
    since: date | None,
    until: date | None,
    limit: int,
    offset: int,
) -> list[AuditEntry]:
    stmt = select(AuditEntry)
    if action:
        # «auth.» выбирает всю группу, «auth.login» только вход
        stmt = stmt.where(AuditEntry.action.startswith(action) if action.endswith(".") else AuditEntry.action == action)
    if actor:
        stmt = stmt.where(AuditEntry.actor == actor)
    if since:
        stmt = stmt.where(AuditEntry.at >= datetime.combine(since, time.min, tzinfo=UTC))
    if until:
        stmt = stmt.where(AuditEntry.at < datetime.combine(until + timedelta(days=1), time.min, tzinfo=UTC))
    return list(db.scalars(stmt.order_by(AuditEntry.id.desc()).limit(limit).offset(offset)))
