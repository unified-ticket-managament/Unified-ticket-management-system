from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from shared_models.models import User

from app.database.session import get_db
from app.dependencies.auth import get_current_agent
from app.repositories.attachment_repository import AttachmentRepository
from app.repositories.client_repository import ClientRepository
from app.repositories.interaction_repository import (
    InteractionRepository,
)
from app.repositories.ticket_repository import TicketRepository
from app.repositories.user_repository import UserRepository
from app.schemas.inbox import InboxResponse
from app.schemas.open_email import OpenEmailResponse
from app.schemas.ticket_action import (
    InteractionReplyRequest,
    InteractionReplyResponse,
)
from app.services.inbox_service import InboxService
from app.services.open_email_service import OpenEmailService
from app.services.interaction_service import InteractionService
from app.storage import get_storage_service

router = APIRouter(
    prefix="/inbox",
    tags=["Inbox"],
)


# ---------------------------------------------------------
# Account Manager Inbox
# ---------------------------------------------------------

@router.get(
    "",
    response_model=InboxResponse,
)
async def get_inbox(
    client_id: UUID | None = Query(default=None),
    view: str = Query(default="pending", pattern="^(pending|replied|ticketed|all)$"),
    scope: str = Query(default="mine", pattern="^(mine|all)$"),
    current_user: User = Depends(get_current_agent),
    db: AsyncSession = Depends(get_db),
):
    """
    Returns the mail belonging to the clients the authenticated user
    manages.

    `view` selects which root emails: not-yet-actioned ("pending"),
    replied-but-never-ticketed ("replied"), promoted-to-a-ticket
    ("ticketed"), or every one of them ("all").

    `scope="all"` is the "All Inboxes" escape hatch — every client's
    mail, not just this user's own. Only takes effect for Manager /
    Super Admin; ignored for anyone else.
    """

    repository = InteractionRepository(db)
    attachment_repository = AttachmentRepository(db)

    service = InboxService(repository, attachment_repository=attachment_repository)

    return await service.get_inbox(
        current_user,
        client_id=client_id,
        view=view,
        scope=scope,
    )


# ---------------------------------------------------------
# Open Email / Thread
# ---------------------------------------------------------

@router.get(
    "/{interaction_id}",
    response_model=OpenEmailResponse,
)
async def open_email(
    interaction_id: UUID,
    current_user: User = Depends(get_current_agent),
    db: AsyncSession = Depends(get_db),
):
    """
    Returns the complete details of one inbox email, plus every
    reply already filed under it.
    """

    repository = InteractionRepository(db)
    attachment_repository = AttachmentRepository(db)

    service = OpenEmailService(
        repository,
        attachment_repository=attachment_repository,
        storage_service=get_storage_service(),
    )

    return await service.get_email_details(
        interaction_id=interaction_id,
    )


# ---------------------------------------------------------
# Reply (bare interaction — no ticket)
# ---------------------------------------------------------

@router.post(
    "/{interaction_id}/reply",
    response_model=InteractionReplyResponse,
    status_code=201,
)
async def reply_to_interaction(
    interaction_id: UUID,
    request: InteractionReplyRequest,
    current_user: User = Depends(get_current_agent),
    db: AsyncSession = Depends(get_db),
):
    """
    Replies to a client on an inbox conversation that hasn't become
    a ticket — the "general communication" path (e.g. "are you
    working today?" -> reply -> done, no ticket needed).
    """

    interaction_repository = InteractionRepository(db)
    ticket_repository = TicketRepository(db)
    user_repository = UserRepository(db)
    client_repository = ClientRepository(db)

    service = InteractionService(
        interaction_repository=interaction_repository,
        ticket_repository=ticket_repository,
        user_repository=user_repository,
        client_repository=client_repository,
    )

    return await service.add_interaction_reply(
        interaction_id=interaction_id,
        request=request,
        current_user=current_user,
    )
