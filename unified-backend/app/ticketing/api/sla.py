from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from shared_models.models import User

from app.database.session import get_db
from app.dependencies.auth import get_current_agent, get_current_user
from app.ticketing.repositories.client_repository import ClientRepository
from app.ticketing.repositories.ticket_repository import TicketRepository
from app.ticketing.schemas.sla import (
    SLAPauseRequest,
    SLAPolicyResponse,
    SLAPolicyUpdate,
    TicketSLAResponse,
)
from app.ticketing.schemas.ticket_action import TicketActionResponse
from app.ticketing.services.access_control import (
    ensure_account_manager_owns_ticket_client,
    ensure_agent_can_view_ticket,
)
from app.ticketing.services.sla_service import build_sla_service

#sla.py

# ---------------------------------------------------------
# Ticket-scoped SLA routes — mounted under /tickets alongside
# app/ticketing/api/ticket.py's own router, kept in a separate file/
# router object so that file doesn't keep growing.
# ---------------------------------------------------------

ticket_sla_router = APIRouter(
    prefix="/tickets",
    tags=["SLA"],
)


@ticket_sla_router.get(
    "/{ticket_id}/sla",
    response_model=TicketSLAResponse,
    status_code=status.HTTP_200_OK,
)
async def get_ticket_sla(
    ticket_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Returns the current state of both SLA clocks for a ticket (status,
    due_at, paused time, elapsed fraction) — computed lazily at read
    time, matching this codebase's existing snoozed_until/expires_at
    idiom. See SLAService.get_ticket_sla_state for why `first_response`
    is always null here.
    """

    ticket_repository = TicketRepository(db)
    client_repository = ClientRepository(db)

    ticket = await ticket_repository.get_by_id(ticket_id)
    if ticket is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Ticket not found."
        )

    ensure_agent_can_view_ticket(ticket, current_user)
    await ensure_account_manager_owns_ticket_client(
        ticket, current_user, client_repository
    )

    sla_service = build_sla_service(db)
    return await sla_service.get_ticket_sla_state(ticket_id=ticket_id)


@ticket_sla_router.post(
    "/{ticket_id}/sla/pause",
    response_model=TicketActionResponse,
    status_code=status.HTTP_200_OK,
)
async def pause_ticket_sla(
    ticket_id: UUID,
    request: SLAPauseRequest,
    current_user: User = Depends(get_current_agent),
    db: AsyncSession = Depends(get_db),
):
    """
    Manually pauses a ticket's Resolution SLA — a business-exception
    override, restricted to supervisor roles. Follows this repo's
    add-ticket-action recipe (Interaction + AuditLog rows).
    """

    sla_service = build_sla_service(db)
    return await sla_service.manual_pause(ticket_id, request, current_user)


@ticket_sla_router.post(
    "/{ticket_id}/sla/resume",
    response_model=TicketActionResponse,
    status_code=status.HTTP_200_OK,
)
async def resume_ticket_sla(
    ticket_id: UUID,
    current_user: User = Depends(get_current_agent),
    db: AsyncSession = Depends(get_db),
):
    """Manually resumes a manually-paused ticket's Resolution SLA."""

    sla_service = build_sla_service(db)
    return await sla_service.manual_resume(ticket_id, current_user)


# ---------------------------------------------------------
# SLA policy admin routes
# ---------------------------------------------------------

sla_policy_router = APIRouter(
    prefix="/sla",
    tags=["SLA"],
)


@sla_policy_router.get(
    "/policies",
    response_model=list[SLAPolicyResponse],
    status_code=status.HTTP_200_OK,
)
async def list_sla_policies(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Returns the three SLA policy rows (one per TicketPriority). Read
    is open to any authenticated user — only PATCH is gated, matching
    this repo's general "read is open, write is gated" bias.
    """

    sla_service = build_sla_service(db)
    return await sla_service.list_policies(current_user)


@sla_policy_router.patch(
    "/policies/{policy_id}",
    response_model=SLAPolicyResponse,
    status_code=status.HTTP_200_OK,
)
async def update_sla_policy(
    policy_id: UUID,
    request: SLAPolicyUpdate,
    current_user: User = Depends(get_current_agent),
    db: AsyncSession = Depends(get_db),
):
    """
    Updates one priority's SLA targets. Restricted to Site Lead/Super
    Admin (sla:manage_policies) — SLA targets are a company-wide
    contractual setting, not per-team config.
    """

    sla_service = build_sla_service(db)
    return await sla_service.update_policy(policy_id, request, current_user)
