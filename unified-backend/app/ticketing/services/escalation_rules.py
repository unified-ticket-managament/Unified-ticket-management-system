from typing import Awaitable, Callable
from uuid import UUID

from app.ticketing.enums import (
    OWNER_ROLE_ASSIGNEE_CHAIN,
    OWNER_ROLE_REPORTING_MANAGER,
    OWNER_ROLE_SITE_LEAD_FALLBACK,
)
from app.ticketing.models.ticket import Ticket
from app.ticketing.services.access_control import STAFF_ROLE_NAME

#escalation_rules.py

# Safety cap on how many hops build_chain_owner_ids will climb before
# giving up — guards against a pathological/cyclic audit trail (e.g.
# A assigns to B, B assigns back to A) turning into an unbounded loop.
# Real assignment chains in this product are expected to be shallow (a
# handful of hops at most); this is generous headroom, not a realistic
# ceiling.
MAX_CHAIN_DEPTH = 10


async def build_chain_owner_ids(ticket: Ticket, audit_log_repository) -> list[UUID]:
    """
    The assignment chain a TicketEscalation climbs if ignored, ordered
    nearest-first: chain[0] is whoever assigned the ticket to its
    current agent_id, chain[1] is whoever assigned *them* the ticket,
    and so on. This — not role hierarchy — is what escalation routing
    now follows (see root CLAUDE.md's "SLA & Escalation" section).

    The first hop comes straight off `Ticket.assigned_by` (the current
    assignment's assigner — a single, current-state field). Every hop
    after that comes from the audit trail
    (`audit_log_repository.find_prior_assigner`), since `assigned_by`
    only ever reflects the *most recent* assignment, never a prior
    one — there is no dedicated assignment-history table, so the
    `AGENT_TRANSFERRED`/`TICKET_CLAIMED` rows in `ticket_audit_logs`
    are the only place that history survives.

    Dead ends fall back to the ticket's own creator (`Ticket.
    created_by`) — per explicit product decision, never to a
    category/role lookup (that would be exactly the role-hierarchy
    routing this chain replaces). Three cases end the chain without
    climbing further, all via the same fallback:
      - An unclaimed ticket (`agent_id is None`) — the chain is just
        `[created_by]`, if one is set, else empty.
      - No recorded assigner for the current hop (`assigned_by is
        None` — e.g. legacy data with no assignment history at all).
      - A self-claim (the hop's own assigner is the same person who
        holds it) — nobody "assigned" them, so there's nothing to
        climb from.
    In both of the latter two cases, `created_by` is only added if it
    isn't the *same* person as the dead-end holder — a ticket created
    and self-assigned by the same person has nobody left to notify at
    all here, and escalation falls all the way back to the terminal
    Site Lead/Super Admin safety net (see `resolve_owners_for_chain`).

    Guarded by a `seen` set (stop on any repeat — a real, if unlikely,
    ping-pong reassignment) and `MAX_CHAIN_DEPTH`.
    """

    seen: set[UUID] = set()
    chain: list[UUID] = []

    def _add(candidate: UUID) -> bool:
        if candidate in seen:
            return False
        chain.append(candidate)
        seen.add(candidate)
        return True

    if ticket.agent_id is None:
        if ticket.created_by is not None:
            _add(ticket.created_by)
        return chain

    holder = ticket.agent_id
    assigner = ticket.assigned_by

    while True:
        if assigner is None or assigner == holder:
            if ticket.created_by is not None and ticket.created_by != holder:
                _add(ticket.created_by)
            return chain

        if not _add(assigner):
            return chain  # cycle detected — stop climbing

        if len(chain) >= MAX_CHAIN_DEPTH:
            return chain

        holder = assigner
        assigner = await audit_log_repository.find_prior_assigner(
            ticket_id=ticket.ticket_id, agent_user_id=assigner
        )


async def resolve_owners_for_chain(
    *,
    ticket: Ticket,
    chain_owner_ids: list[UUID],
    chain_position: int,
    user_repository,
    resolve_site_lead_fallback_ids: Callable[[], Awaitable[set[UUID]]],
) -> dict[UUID, str]:
    """
    The owner -> role-tag map for one escalation step, keyed by user_id.
    `chain_position` indexes into `chain_owner_ids` (built by
    `build_chain_owner_ids` above); `chain_position >= len(...)` means
    the chain is exhausted (or was empty to begin with, e.g. a ticket
    with no `created_by` either) — ownership falls back to the
    terminal Site Lead/Super Admin safety net,
    `resolve_site_lead_fallback_ids()` (injected rather than imported
    directly, so this function needs no UserRepository-shaped
    dependency of its own and stays easy to unit test), tagged
    OWNER_ROLE_SITE_LEAD_FALLBACK.

    Otherwise: `{chain_owner_ids[chain_position]: OWNER_ROLE_ASSIGNEE_CHAIN}`,
    plus — only at `chain_position == 0`, and only when the ticket's
    *current* assignee holds the Staff role — their own
    `reporting_manager_id` as a parallel recipient, tagged
    OWNER_ROLE_REPORTING_MANAGER, unless it's the same person already
    in the chain (e.g. a Staff member whose Team Lead both assigned
    them the ticket AND is their `reporting_manager_id` — one owner,
    not two). Reporting-Manager augmentation never re-applies on later
    hops — it's specifically about the ticket's actual current
    assignee, which doesn't change as the chain climbs past their own
    assigner.
    """

    if chain_position >= len(chain_owner_ids):
        fallback_ids = await resolve_site_lead_fallback_ids()
        return {uid: OWNER_ROLE_SITE_LEAD_FALLBACK for uid in fallback_ids}

    owners: dict[UUID, str] = {chain_owner_ids[chain_position]: OWNER_ROLE_ASSIGNEE_CHAIN}

    if chain_position == 0 and ticket.agent_id is not None:
        assignee = await user_repository.get_by_id(ticket.agent_id)
        if (
            assignee is not None
            and assignee.role is not None
            and assignee.role.name == STAFF_ROLE_NAME
            and assignee.reporting_manager_id is not None
            and assignee.reporting_manager_id not in owners
        ):
            owners[assignee.reporting_manager_id] = OWNER_ROLE_REPORTING_MANAGER

    return owners
