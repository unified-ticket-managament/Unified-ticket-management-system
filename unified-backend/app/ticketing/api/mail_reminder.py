from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status
from shared_models.models import User
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import get_db
from app.dependencies.auth import get_current_agent
from app.ticketing.schemas.mail_reminder import (
    MailReminderCreate,
    MailReminderResponse,
    MailReminderSnooze,
    MailReminderUpdate,
)
from app.ticketing.services.mail_reminder_service import build_mail_reminder_service

# Personal "Remind me" reminders. Every route is scoped to the
# authenticated user (user_id is never read from the request); another
# user's reminder is indistinguishable from a missing one (404).
router = APIRouter(
    prefix="/mail-reminders",
    tags=["Mail Reminders"],
)


async def _commit_before_responding(db: AsyncSession) -> None:
    """
    get_db commits in its dependency cleanup, which FastAPI runs AFTER the
    response has been sent. The UI refetches the reminder list the instant
    a write returns, so without this a read can land before the commit and
    miss (or still show) the row it just changed. Committing here makes a
    2xx mean "durable and visible"; get_db's later commit is then a no-op.
    """

    await db.commit()


@router.post("", response_model=MailReminderResponse, status_code=status.HTTP_201_CREATED)
async def create_mail_reminder(
    request: MailReminderCreate,
    current_user: User = Depends(get_current_agent),
    db: AsyncSession = Depends(get_db),
):
    service = build_mail_reminder_service(db)
    reminder = await service.create(
        current_user, request.interaction_id, request.remind_at
    )
    await _commit_before_responding(db)
    return reminder


@router.get("", response_model=list[MailReminderResponse])
async def list_mail_reminders(
    status_filter: str | None = Query(default=None, alias="status"),
    interaction_id: UUID | None = None,
    current_user: User = Depends(get_current_agent),
    db: AsyncSession = Depends(get_db),
):
    service = build_mail_reminder_service(db)
    return await service.list_reminders(
        current_user, status_filter=status_filter, interaction_id=interaction_id
    )


@router.get("/{reminder_id}", response_model=MailReminderResponse)
async def get_mail_reminder(
    reminder_id: UUID,
    current_user: User = Depends(get_current_agent),
    db: AsyncSession = Depends(get_db),
):
    return await build_mail_reminder_service(db).get(current_user, reminder_id)


@router.patch("/{reminder_id}", response_model=MailReminderResponse)
async def update_mail_reminder(
    reminder_id: UUID,
    request: MailReminderUpdate,
    current_user: User = Depends(get_current_agent),
    db: AsyncSession = Depends(get_db),
):
    reminder = await build_mail_reminder_service(db).update(
        current_user, reminder_id, request.remind_at
    )
    await _commit_before_responding(db)
    return reminder


@router.delete("/{reminder_id}", status_code=status.HTTP_204_NO_CONTENT)
async def cancel_mail_reminder(
    reminder_id: UUID,
    current_user: User = Depends(get_current_agent),
    db: AsyncSession = Depends(get_db),
):
    await build_mail_reminder_service(db).cancel(current_user, reminder_id)
    await _commit_before_responding(db)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{reminder_id}/snooze", response_model=MailReminderResponse)
async def snooze_mail_reminder(
    reminder_id: UUID,
    request: MailReminderSnooze,
    current_user: User = Depends(get_current_agent),
    db: AsyncSession = Depends(get_db),
):
    reminder = await build_mail_reminder_service(db).snooze(
        current_user,
        reminder_id,
        remind_at=request.remind_at,
        minutes=request.minutes,
    )
    await _commit_before_responding(db)
    return reminder


@router.post("/{reminder_id}/dismiss", response_model=MailReminderResponse)
async def dismiss_mail_reminder(
    reminder_id: UUID,
    current_user: User = Depends(get_current_agent),
    db: AsyncSession = Depends(get_db),
):
    reminder = await build_mail_reminder_service(db).dismiss(current_user, reminder_id)
    await _commit_before_responding(db)
    return reminder
