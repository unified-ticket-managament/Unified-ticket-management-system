# helpers.py

from datetime import date, datetime
from enum import Enum
from typing import Any
from uuid import UUID


def serialize_audit_values(
    data: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """
    Makes a dict safe to store in a JSONB column. UUIDs, enums, and
    datetimes aren't JSON-serializable on their own, and asyncpg /
    SQLAlchemy's JSONB type won't convert them for us — inserting
    one directly raises at flush time.
    """

    if data is None:
        return None

    return {key: _serialize_value(value) for key, value in data.items()}


def _serialize_value(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _serialize_value(val) for key, val in value.items()}
    if isinstance(value, (list, tuple)):
        return [_serialize_value(item) for item in value]
    return value
