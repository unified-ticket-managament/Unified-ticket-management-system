# app_settings_service.py
#
# Typed access to the runtime settings an administrator can change from
# the Settings UI (table `app_settings`). The DATABASE is the single
# source of truth: there is deliberately no environment-variable
# counterpart, so there is never a second switch to keep in sync.
#
# Safe by default: a missing row, a non-boolean value, or any failure
# reading the table all mean "OFF". Read Receipts therefore cannot be
# enabled by accident (fresh database, failed migration, bad data) — only
# an explicit, authorized UPDATE turns it on.

import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.ticketing.models.app_setting import AppSetting

logger = logging.getLogger(__name__)

# The ONLY keys this module reads or writes.
READ_RECEIPTS_ENABLED_KEY = "read_receipts_enabled"

# Existing permission (seeded for Super Admin only by default):
# "Configure ticket system and storage settings". Reused rather than
# adding a new permission — see the Read Receipts docs.
APP_SETTINGS_MANAGE_PERMISSION = "ticket:system_config"


async def is_read_receipts_enabled(db: AsyncSession) -> bool:
    """
    The global Read Receipts switch. OFF unless an administrator has
    explicitly turned it on. Never raises: any problem reading the table
    fails CLOSED (OFF), inside a savepoint so it cannot poison the
    caller's transaction.
    """

    try:
        async with db.begin_nested():
            value = (
                await db.execute(
                    select(AppSetting.value).where(
                        AppSetting.key == READ_RECEIPTS_ENABLED_KEY
                    )
                )
            ).scalar_one_or_none()
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "read-receipts setting lookup failed (treated as OFF): error=%s",
            type(exc).__name__,
        )
        return False

    return value is True


async def set_read_receipts_enabled(
    db: AsyncSession, enabled: bool, updated_by: uuid.UUID | None
) -> bool:
    """
    Upserts the Read Receipts switch (caller has already authorized the
    change) and returns the stored value. Flushes only; the caller owns
    the transaction.
    """

    now = datetime.now(timezone.utc)
    stmt = pg_insert(AppSetting).values(
        key=READ_RECEIPTS_ENABLED_KEY,
        value=bool(enabled),
        updated_by=updated_by,
        updated_at=now,
    )
    await db.execute(
        stmt.on_conflict_do_update(
            index_elements=[AppSetting.key],
            set_={"value": bool(enabled), "updated_by": updated_by, "updated_at": now},
        )
    )
    await db.flush()
    return bool(enabled)
