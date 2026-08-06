# email_content.py

import html
from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

if TYPE_CHECKING:
    from app.notifications.models import Notification


@dataclass(frozen=True)
class TicketEmailContext:
    ticket_id: UUID
    priority: str | None
    status: str | None
    client_name: str | None


async def load_ticket_context(
    db: AsyncSession, *, related_entity_type: str | None, related_entity_id: UUID | None
) -> TicketEmailContext | None:
    """
    Best-effort ticket lookup for the email body's Ticket ID/Client
    name/Priority/Current Status fields — "if applicable" per the
    email policy's own requirements, since not every notification type
    is ticket-shaped (e.g. edit-access notifications key their
    related_entity_id off the edit-access request, not the ticket) and
    the Notification row itself carries no such columns. Deferred
    import of the ticketing models: app.notifications is a shared,
    cross-cutting module used by both app.rbac and app.ticketing (see
    app/notifications/service.py's own docstring), and app.ticketing
    already imports app.notifications, so a module-level import here
    would be circular.
    """

    if related_entity_type != "ticket" or related_entity_id is None:
        return None

    from app.ticketing.models.client import Client
    from app.ticketing.models.ticket import Ticket

    result = await db.execute(
        select(Ticket, Client)
        .outerjoin(Client, Client.client_id == Ticket.client_company_id)
        .where(Ticket.ticket_id == related_entity_id)
    )
    row = result.first()
    if row is None:
        return None

    ticket, client = row
    return TicketEmailContext(
        ticket_id=ticket.ticket_id,
        priority=getattr(ticket.current_priority, "value", None),
        status=getattr(ticket.current_status, "value", None),
        client_name=client.name if client is not None else None,
    )


def build_notification_email(
    notification: "Notification", ticket_context: TicketEmailContext | None
) -> tuple[str, str, str]:
    """
    Builds (subject, text_body, html_body) for one notification's
    outbound email. Every field below is per the feature's own "Email
    Requirements": title, message, ticket id, client name, priority,
    current status, timestamp — the last four rendered as "Not
    applicable" when there's no resolvable ticket context, rather than
    omitted, so the email layout never shifts between notification
    types.
    """

    subject = notification.title

    ticket_id = str(ticket_context.ticket_id) if ticket_context else "Not applicable"
    client_name = (ticket_context.client_name if ticket_context else None) or "Not applicable"
    priority = (ticket_context.priority if ticket_context else None) or "Not applicable"
    status = (ticket_context.status if ticket_context else None) or "Not applicable"
    timestamp = notification.created_at.isoformat()

    text_body = (
        f"{notification.title}\n\n"
        f"{notification.message}\n\n"
        f"Ticket ID: {ticket_id}\n"
        f"Client: {client_name}\n"
        f"Priority: {priority}\n"
        f"Status: {status}\n"
        f"Timestamp: {timestamp}\n"
    )

    e = html.escape
    html_body = f"""\
<div style="font-family: sans-serif; max-width: 560px;">
  <h2 style="margin-bottom: 4px;">{e(notification.title)}</h2>
  <p style="white-space: pre-wrap;">{e(notification.message)}</p>
  <table style="border-collapse: collapse; margin-top: 12px;">
    <tr><td style="padding: 4px 12px 4px 0; color: #555;">Ticket ID</td><td>{e(ticket_id)}</td></tr>
    <tr><td style="padding: 4px 12px 4px 0; color: #555;">Client</td><td>{e(client_name)}</td></tr>
    <tr><td style="padding: 4px 12px 4px 0; color: #555;">Priority</td><td>{e(priority)}</td></tr>
    <tr><td style="padding: 4px 12px 4px 0; color: #555;">Status</td><td>{e(status)}</td></tr>
    <tr><td style="padding: 4px 12px 4px 0; color: #555;">Timestamp</td><td>{e(timestamp)}</td></tr>
  </table>
</div>
"""

    return subject, text_body, html_body
