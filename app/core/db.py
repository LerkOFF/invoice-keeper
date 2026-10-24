from collections.abc import Iterator
from pathlib import Path

from sqlalchemy import Engine, create_engine, event, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import get_settings


class Base(DeclarativeBase):
    pass


def build_engine(database_url: str) -> Engine:
    url = make_url(database_url)
    connect_args: dict = {}
    if url.get_backend_name() == "sqlite":
        connect_args["check_same_thread"] = False
        if url.database and url.database != ":memory:":
            Path(url.database).parent.mkdir(parents=True, exist_ok=True)

    engine = create_engine(url, connect_args=connect_args)

    if url.get_backend_name() == "sqlite":

        @event.listens_for(engine, "connect")
        def _enable_foreign_keys(dbapi_connection, _record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return engine


engine = build_engine(get_settings().database_url)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def init_db(target: Engine | None = None) -> None:
    """Создаёт схему, если её ещё нет, и доводит старую базу до текущей схемы."""
    import app.models  # noqa: F401  регистрирует модели в Base.metadata

    target = target or engine
    Base.metadata.create_all(target)
    migrate(target)


def migrate(target: Engine) -> None:
    """create_all не добавляет колонки в существующие таблицы, поэтому новые колонки добавляем здесь.

    Каждый шаг идемпотентен: повторный запуск ничего не меняет.
    """
    with target.begin() as conn:
        columns = {column["name"] for column in inspect(conn).get_columns("payment_occurrences")}
        if "amount_minor" not in columns:
            conn.execute(text("ALTER TABLE payment_occurrences ADD COLUMN amount_minor INTEGER"))
        if "overdue_reminded_at" not in columns:
            conn.execute(text("ALTER TABLE payment_occurrences ADD COLUMN overdue_reminded_at DATETIME"))
        # периоды из старой базы получают текущую сумму своего платежа
        conn.execute(
            text(
                "UPDATE payment_occurrences SET amount_minor = (SELECT r.amount_minor FROM recurring_payments r "
                "WHERE r.id = payment_occurrences.recurring_id) WHERE amount_minor IS NULL"
            )
        )

        payment_columns = {column["name"] for column in inspect(conn).get_columns("recurring_payments")}
        if "pay_url" not in payment_columns:
            conn.execute(text("ALTER TABLE recurring_payments ADD COLUMN pay_url VARCHAR(500)"))
        if "pay_details" not in payment_columns:
            conn.execute(text("ALTER TABLE recurring_payments ADD COLUMN pay_details VARCHAR(1000)"))
        if "category" not in payment_columns:
            conn.execute(text("ALTER TABLE recurring_payments ADD COLUMN category VARCHAR(60)"))

        has_receipts = inspect(conn).has_table("occurrence_receipts")
        receipt_columns = {c["name"] for c in inspect(conn).get_columns("occurrence_receipts")} if has_receipts else set()
        if has_receipts and "created_by_user_id" not in receipt_columns:
            conn.execute(
                text(
                    "ALTER TABLE occurrence_receipts ADD COLUMN created_by_user_id INTEGER "
                    "REFERENCES users(id) ON DELETE SET NULL"
                )
            )
            # один раз, при добавлении колонки: старые вложения пользователей находят автора по логину
            conn.execute(
                text(
                    "UPDATE occurrence_receipts SET created_by_user_id = (SELECT u.id FROM users u "
                    "WHERE u.login = occurrence_receipts.created_by) WHERE created_by_type = 'user'"
                )
            )


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
