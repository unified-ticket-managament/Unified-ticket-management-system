# email_content.py

import html
from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.notifications.service import NotificationType

if TYPE_CHECKING:
    from app.notifications.models import Notification


@dataclass(frozen=True)
class TicketEmailContext:
    ticket_id: UUID
    title: str
    priority: str | None
    status: str | None
    client_name: str | None
    assigned_to_name: str | None
    assigned_by_name: str | None


async def load_ticket_context(
    db: AsyncSession, *, related_entity_type: str | None, related_entity_id: UUID | None
) -> TicketEmailContext | None:
    """
    Best-effort ticket lookup for the email body's Ticket/Client
    name/Priority/Current Status/Assigned-to/Assigned-by fields — "if
    applicable" per the email policy's own requirements, since not
    every notification type is ticket-shaped and the Notification row
    itself carries no such columns. Deferred import of the ticketing
    models: app.notifications is a shared, cross-cutting module used
    by both app.rbac and app.ticketing (see app/notifications/
    service.py's own docstring), and app.ticketing already imports
    app.notifications, so a module-level import here would be
    circular.
    """

    if related_entity_type != "ticket" or related_entity_id is None:
        return None

    from shared_models.models import User

    from app.ticketing.models.client import Client
    from app.ticketing.models.ticket import Ticket

    AgentUser = aliased(User)
    AssignedByUser = aliased(User)

    result = await db.execute(
        select(Ticket, Client, AgentUser, AssignedByUser)
        .outerjoin(Client, Client.client_id == Ticket.client_company_id)
        .outerjoin(AgentUser, AgentUser.user_id == Ticket.agent_id)
        .outerjoin(AssignedByUser, AssignedByUser.user_id == Ticket.assigned_by)
        .where(Ticket.ticket_id == related_entity_id)
    )
    row = result.first()
    if row is None:
        return None

    ticket, client, agent_user, assigned_by_user = row
    return TicketEmailContext(
        ticket_id=ticket.ticket_id,
        title=ticket.title,
        priority=getattr(ticket.current_priority, "value", None),
        status=getattr(ticket.current_status, "value", None),
        client_name=client.name if client is not None else None,
        assigned_to_name=agent_user.name if agent_user is not None else None,
        assigned_by_name=assigned_by_user.name if assigned_by_user is not None else None,
    )


def _build_fields(
    notification: "Notification", ticket_context: TicketEmailContext | None
) -> list[tuple[str, str]]:
    """
    Ordered (label, value) pairs for the email body — real data only,
    never a placeholder. A field with no value (no client on the
    ticket, an unassigned ticket, no resolvable ticket at all) is left
    out of this list entirely rather than rendered as "Not applicable"/
    "N/A"/"Unknown", so text_body/html_body can never show one.
    "Assigned to"/"Assigned by"/"Assigned at" only apply to the
    assignment notification itself — they wouldn't mean anything on an
    escalation or client-reply email, which get the existing generic
    "Timestamp" instead.
    """

    timestamp = notification.created_at.isoformat()

    if ticket_context is None:
        return [("Timestamp", timestamp)]

    fields: list[tuple[str, str]] = [("Ticket", ticket_context.title)]
    if ticket_context.client_name:
        fields.append(("Client", ticket_context.client_name))
    if ticket_context.priority:
        fields.append(("Priority", ticket_context.priority))
    if ticket_context.status:
        fields.append(("Status", ticket_context.status))

    if notification.notification_type == NotificationType.TICKET_ASSIGNED:
        if ticket_context.assigned_to_name:
            fields.append(("Assigned to", ticket_context.assigned_to_name))
        if ticket_context.assigned_by_name:
            fields.append(("Assigned by", ticket_context.assigned_by_name))
        fields.append(("Assigned at", timestamp))
    else:
        fields.append(("Timestamp", timestamp))

    return fields


def build_notification_email(
    notification: "Notification", ticket_context: TicketEmailContext | None
) -> tuple[str, str, str]:
    """
    Builds (subject, text_body, html_body) for one notification's
    outbound email from real ticket/assignment data only — see
    _build_fields for the omit-rather-than-placeholder rule. The
    internal Ticket UUID is never included; it's an implementation
    detail, not user-facing content.
    """

    subject = notification.title
    fields = _build_fields(notification, ticket_context)

    text_body = (
        f"{notification.title}\n\n"
        f"{notification.message}\n\n"
        + "".join(f"{label}: {value}\n" for label, value in fields)
    )

    e = html.escape
    rows = "".join(
        f'    <tr><td style="padding: 4px 12px 4px 0; color: #555;">{e(label)}</td>'
        f"<td>{e(value)}</td></tr>\n"
        for label, value in fields
    )
    html_body = f"""\
<div style="font-family: sans-serif; max-width: 560px;">
  <h2 style="margin-bottom: 4px;">{e(notification.title)}</h2>
  <p style="white-space: pre-wrap;">{e(notification.message)}</p>
  <table style="border-collapse: collapse; margin-top: 12px;">
{rows}  </table>
</div>
"""

    return subject, text_body, html_body
