import logging

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from shared_models.models import User
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import get_db
from app.dependencies.auth import get_current_agent
from app.rbac.repositories.audit_log_repository import AuditLogRepository
from app.rbac.schemas.audit_log import AuditLogCreate
from app.rbac.services.audit_log_service import AuditLogService
from app.ticketing.services.access_control import ensure_has_permission, has_permission
from app.ticketing.services.app_settings_service import (
    APP_SETTINGS_MANAGE_PERMISSION,
    READ_RECEIPTS_ENABLED_KEY,
    is_read_receipts_enabled,
    set_read_receipts_enabled,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/app-settings",
    tags=["App Settings"],
)


class ReadReceiptSettingResponse(BaseModel):
    # The global switch. OFF unless an administrator turned it on.
    read_receipts_enabled: bool
    # Whether THIS caller may change it (so the UI can disable the toggle
    # for everyone else). The server re-checks on every update.
    can_manage: bool


class ReadReceiptSettingUpdate(BaseModel):
    enabled: bool


@router.get("/read-receipts", response_model=ReadReceiptSettingResponse)
async def get_read_receipt_setting(
    current_user: User = Depends(get_current_agent),
    db: AsyncSession = Depends(get_db),
):
    """
    Current Read Receipts setting. Readable by any authenticated agent
    (the composers need it to show/hide the checkbox); only
    `ticket:system_config` holders can change it.
    """

    return ReadReceiptSettingResponse(
        read_receipts_enabled=await is_read_receipts_enabled(db),
        can_manage=has_permission(current_user, APP_SETTINGS_MANAGE_PERMISSION),
    )


@router.put("/read-receipts", response_model=ReadReceiptSettingResponse)
async def update_read_receipt_setting(
    body: ReadReceiptSettingUpdate,
    current_user: User = Depends(get_current_agent),
    db: AsyncSession = Depends(get_db),
):
    """
    Turn Read Receipts on or off for the whole system. Requires the
    existing `ticket:system_config` permission (Super Admin by default) —
    NOT granted to Staff or other roles automatically. Agents who may send
    external email can USE the feature when it is on; they cannot change
    this switch. The change is recorded in the RBAC audit log.
    """

    ensure_has_permission(current_user, APP_SETTINGS_MANAGE_PERMISSION)

    previous = await is_read_receipts_enabled(db)
    stored = await set_read_receipts_enabled(db, body.enabled, current_user.user_id)

    try:
        async with db.begin_nested():
            await AuditLogService(
                audit_log_repository=AuditLogRepository(db)
            ).create_log(
                AuditLogCreate(
                    user_id=current_user.user_id,
                    action="settings.read_receipts_updated",
                    entity_type="app_setting",
                    entity_id=READ_RECEIPTS_ENABLED_KEY,
                    old_value=str(previous).lower(),
                    new_value=str(stored).lower(),
                )
            )
    except Exception as exc:  # noqa: BLE001 — never lose the setting change over bookkeeping
        logger.warning(
            "audit log for read-receipts setting change failed: error=%s",
            type(exc).__name__,
        )

    return ReadReceiptSettingResponse(
        read_receipts_enabled=stored,
        can_manage=True,
    )
