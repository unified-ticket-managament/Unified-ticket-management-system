"""
Shared keyset ("cursor") pagination helpers for list endpoints that
already support OFFSET/LIMIT paging (GET /tickets/interactions,
GET /inbox).

OFFSET pagination is O(offset) — Postgres must traverse and discard
`offset` rows before returning a page, even with a perfect index. At
dev-scale (hundreds of rows) that's immeasurable; at production scale
(millions of interactions/audit rows), a deep page becomes genuinely
expensive. Cursor/keyset pagination is O(limit) regardless of depth:
instead of "skip N rows", the next page is requested as "give me rows
older than the last one I saw" — a plain indexed range condition.

This is added as an ADDITIVE alternative, not a replacement: every
existing caller that only passes `limit`/`offset` keeps working
exactly as before (this module isn't invoked at all unless a caller
opts in by passing `cursor`). The opaque cursor string encodes
`(sort_value, row_id)` — the row_id tiebreaker is required because
`created_at`/`received_at` alone is not guaranteed unique, and without
a stable tiebreaker two rows sharing a timestamp could be skipped or
repeated across pages.
"""

import base64
from datetime import datetime
from uuid import UUID


class InvalidCursorError(ValueError):
    """Raised when a cursor string is malformed or doesn't decode cleanly."""


def encode_cursor(sort_value: datetime, row_id: UUID) -> str:
    raw = f"{sort_value.isoformat()}|{row_id}"
    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii")


def decode_cursor(cursor: str) -> tuple[datetime, UUID]:
    try:
        raw = base64.urlsafe_b64decode(cursor.encode("ascii")).decode("utf-8")
        sort_value_str, row_id_str = raw.split("|", 1)
        return datetime.fromisoformat(sort_value_str), UUID(row_id_str)
    except (ValueError, TypeError) as exc:
        raise InvalidCursorError(f"Invalid pagination cursor: {cursor!r}") from exc
