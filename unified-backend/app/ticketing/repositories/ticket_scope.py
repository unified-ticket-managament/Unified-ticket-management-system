"""
Shared SQL conditions for multi-user / multi-category tickets.

Every list/count/filter that used to compare the single legacy column
(`Ticket.agent_id == X`, `Ticket.ticket_type IN (...)`) goes through one
of these instead, so "assigned to me" and "in my categories" mean the
same thing everywhere. Each keeps the legacy column as an OR branch, so
a ticket whose new rows haven't been written (a ticket created by code
that predates them, or a test fixture) is never accidentally hidden.

All are correlated EXISTS (never JOINs), so they can't fan out rows or
break COUNT(*) OVER () on the paged list.
"""

from uuid import UUID

from sqlalchemy import and_, exists, or_
from shared_models.models import Category

from app.ticketing.models.ticket import Ticket
from app.ticketing.models.ticket_assignment import TicketAssignment
from app.ticketing.models.ticket_category import TicketCategory


def ticket_in_categories(category_names, ticket_entity=Ticket):
    """
    Ticket belongs to ANY of `category_names` (primary or secondary).
    `ticket_entity` lets a caller pass an aliased Ticket.
    """

    return or_(
        ticket_entity.ticket_type.in_(category_names),
        exists().where(
            TicketCategory.ticket_id == ticket_entity.ticket_id,
            TicketCategory.category_id == Category.category_id,
            Category.category_name.in_(category_names),
        ),
    )


def ticket_has_category(category_name: str):
    """Single-category filter (the existing ticket_type filter param)."""

    return ticket_in_categories([category_name])


def ticket_assigned_to(user_id: UUID, *, primary_only: bool = False):
    """
    Ticket is assigned to `user_id`. primary_only=True keeps the legacy
    meaning exactly (Ticket.agent_id is the primary projection).
    """

    if primary_only:
        return Ticket.agent_id == user_id
    return or_(
        Ticket.agent_id == user_id,
        exists().where(
            TicketAssignment.ticket_id == Ticket.ticket_id,
            TicketAssignment.user_id == user_id,
            TicketAssignment.removed_at.is_(None),
        ),
    )


def ticket_assigned_to_any(user_ids):
    """Ticket is assigned (primary or secondary) to any of `user_ids`."""

    return or_(
        Ticket.agent_id.in_(user_ids),
        exists().where(
            TicketAssignment.ticket_id == Ticket.ticket_id,
            TicketAssignment.user_id.in_(user_ids),
            TicketAssignment.removed_at.is_(None),
        ),
    )


def ticket_has_assignment_status(status, *, user_id: UUID | None = None):
    """Some active assignment (optionally: this user's) is in `status`."""

    conditions = [
        TicketAssignment.ticket_id == Ticket.ticket_id,
        TicketAssignment.removed_at.is_(None),
        TicketAssignment.status == status,
    ]
    if user_id is not None:
        conditions.append(TicketAssignment.user_id == user_id)
    return exists().where(and_(*conditions))
