# forward_access.py
"""
Shared "was this user actually named as a recipient of a Forward
action anywhere on this thread" check — the single source of truth
for the manual-forward/Rule-forward recipient access widening, reused
by InteractionService (action authorization: reply/forward/the four
draft actions, via `permission_backed`/`is_forward_recipient` on
ensure_agent_can_view_pending_interaction/ensure_agent_can_act_on_
ticket) and OpenEmailService (viewing, same `is_forward_recipient`
flag under `view_only=True`). Do not reimplement this check a second
time anywhere else.

Deliberately indifferent to *how* a FORWARD-type Interaction row was
created — manual forward (InteractionService.forward_to_internal_user)
and Rule forward (RuleEngineService._forward_to_employees) both write
the identical `interaction_type="FORWARD"` + `payload["recipients"]`
shape, so this one predicate covers both without needing to know
which produced any given row.
"""

from uuid import UUID

from shared_models.models import User

from app.ticketing.models.interaction import Interaction
from app.ticketing.repositories.interaction_repository import InteractionRepository


def thread_has_forward_recipient(
    thread: list[Interaction], current_user: User
) -> bool:
    """
    True if `current_user` is named in `payload["recipients"]` on any
    FORWARD-type row in `thread` — checks every such row, and every
    recipient within each, so multiple forwards and/or multiple
    recipients per forward are both already handled correctly.
    """

    user_id_str = str(current_user.user_id)
    for candidate in thread:
        if candidate.interaction_type != "FORWARD":
            continue
        recipients = (candidate.payload or {}).get("recipients") or []
        if any(r.get("user_id") == user_id_str for r in recipients):
            return True
    return False


async def is_ticket_forward_recipient(
    interaction_repository: InteractionRepository,
    ticket_id: UUID,
    current_user: User,
) -> bool:
    """
    Same rule as `is_forwarded_to_user`, entered directly from a
    ticket_id — used once a thread has already been ticketed, where
    every Interaction on it (the Forward row included) shares that
    same ticket_id, so `list_by_ticket_id` finds it directly.
    """

    thread = await interaction_repository.list_by_ticket_id(ticket_id)
    return thread_has_forward_recipient(thread, current_user)


async def is_forwarded_to_user(
    interaction_repository: InteractionRepository,
    interaction: Interaction,
    current_user: User,
) -> bool:
    """
    True if `current_user` was named as a recipient of a Forward
    action anywhere on `interaction`'s own thread. Checks the whole
    thread, not just `interaction` itself — a Forward always creates
    its own new sibling Interaction row rather than mutating the
    message forwarded, so the forward-naming row and the interaction
    being opened/acted on are frequently two different rows in the
    same thread.
    """

    if interaction.ticket_id is not None:
        return await is_ticket_forward_recipient(
            interaction_repository, interaction.ticket_id, current_user
        )

    root = await interaction_repository.find_thread_root(interaction.interaction_id)
    root_id = root.interaction_id if root is not None else interaction.interaction_id
    thread = await interaction_repository.list_thread(root_id)
    if root is not None:
        thread = [root, *thread]

    return thread_has_forward_recipient(thread, current_user)
