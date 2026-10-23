from datetime import UTC, datetime
from typing import Annotated

from pydantic import PlainSerializer


def _as_utc(value: datetime) -> str:
    # SQLite отдаёт время без пояса, в базу мы всегда пишем UTC
    aware = value if value.tzinfo else value.replace(tzinfo=UTC)
    return aware.astimezone(UTC).isoformat().replace("+00:00", "Z")


UtcDateTime = Annotated[datetime, PlainSerializer(_as_utc, return_type=str, when_used="json")]
