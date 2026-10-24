"""Двухфакторный вход администратора: откуда берётся секрет и как включить его из панели.

Секрет из .env (ADMIN_TOTP_SECRET) главнее: пока он задан, панель его не меняет.
Без него секрет хранится в таблице admin_two_factor. Панель выдаёт новый секрет и QR-код,
администратор добавляет его в приложение-аутентификатор и подтверждает кодом: только после этого вход требует код.

Потерян телефон: на сервере `docker compose exec app python -m app.services.two_factor off`
выключает второй фактор, включённый из панели.
"""
import sys
from datetime import UTC, datetime
from typing import Literal

import segno
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models import AdminTwoFactor
from app.services.totp import admin_otp, generate_secret

Source = Literal["env", "panel"]
_ROW_ID = 1


class SetupError(Exception):
    """Настройку нельзя продолжить: роутер превращает это в ответ с понятным текстом."""


def _row(db: Session) -> AdminTwoFactor | None:
    return db.get(AdminTwoFactor, _ROW_ID)


def source(db: Session, settings: Settings) -> Source | None:
    """Где задан действующий секрет: в .env, в панели или нигде (второй фактор выключен)."""
    if settings.admin_totp_secret:
        return "env"
    row = _row(db)
    return "panel" if row is not None and row.secret else None


def secret(db: Session, settings: Settings) -> str:
    """Действующий секрет администратора или пустая строка."""
    if settings.admin_totp_secret:
        return settings.admin_totp_secret
    row = _row(db)
    return row.secret if row is not None and row.secret else ""


def enabled_at(db: Session, settings: Settings) -> datetime | None:
    if settings.admin_totp_secret:
        return None
    row = _row(db)
    return row.enabled_at if row is not None and row.secret else None


def qr_rows(text: str) -> list[str]:
    """QR-код строками из 0 и 1, без поля вокруг. Панель рисует его сама, без картинок и сторонних сервисов."""
    matrix = segno.make(text, error="m", micro=False).matrix
    return ["".join("1" if cell else "0" for cell in row) for row in matrix]


def start_setup(db: Session) -> str:
    """Новый секрет для настройки. Вход не меняется, пока секрет не подтверждён кодом."""
    row = _row(db)
    if row is None:
        row = AdminTwoFactor(id=_ROW_ID)
        db.add(row)
    row.pending_secret = generate_secret()
    return row.pending_secret


def confirm_setup(db: Session, code: str) -> bool:
    """Код из приложения подтверждает, что секрет сохранён. Тогда второй фактор включается."""
    row = _row(db)
    if row is None or not row.pending_secret:
        raise SetupError("Сначала начните настройку: получите новый секрет")
    if not admin_otp.verify(row.pending_secret, code):
        return False
    row.secret, row.pending_secret, row.enabled_at = row.pending_secret, None, datetime.now(UTC)
    return True


def disable(db: Session) -> bool:
    """Выключает второй фактор, включённый из панели. Возвращает, был ли он включён."""
    row = _row(db)
    if row is None or not (row.secret or row.pending_secret):
        return False
    was_on = bool(row.secret)
    row.secret, row.pending_secret, row.enabled_at = None, None, None
    return was_on


def main(argv: list[str]) -> int:
    if argv != ["off"]:
        print("Использование: python -m app.services.two_factor off")
        print("Выключает двухфакторный вход администратора, включённый из панели (например, если потерян телефон).")
        return 2
    from app.core.db import SessionLocal, init_db

    init_db()
    with SessionLocal() as db:
        was_on = disable(db)
        db.commit()
    print("Двухфакторный вход из панели выключен." if was_on else "Двухфакторный вход из панели и так выключен.")
    print("Если задан ADMIN_TOTP_SECRET в .env, он продолжает действовать: уберите строку и перезапустите приложение.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
