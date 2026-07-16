# audit_to_interaction.py

from uuid import UUID

from app.ticketing.enums import AuditEventType, InteractionDirection, InteractionStatus
from app.ticketing.models.audit_log import AuditLog
from app.ticketing.schemas.interaction import TicketInteractionResponse

# STATUS_CHANGE/PRIORITY_CHANGE/AGENT_TRANSFER/CLAIM/EDIT_ACCESS_* no
# longer get their own Interaction row (see interaction_service.py/
# edit_access_service.py) — the ticket_audit_logs row written in the
# same method, at the same time, is now their only record. This maps
# each retired AuditEventType back onto the interaction_type string
# the frontend's lib/interactionMeta.ts already knows how to render,
# so the Timeline/Interactions-list endpoints can synthesize a
# display row from it with zero frontend changes.
#
# ATTACHMENT_UPLOADED is deliberately absent — ATTACHMENT keeps
# creating a real Interaction row (it's the uploaded file's only
# anchor), so synthesizing it too would double up every upload.
_EVENT_TO_INTERACTION_TYPE: dict[AuditEventType, str] = {
    AuditEventType.STATUS_CHANGED: "STATUS_CHANGE",
    AuditEventType.PRIORITY_CHANGED: "PRIORITY_CHANGE",
    AuditEventType.AGENT_TRANSFERRED: "AGENT_TRANSFER",
    AuditEventType.TICKET_CLAIMED: "CLAIM",
    AuditEventType.EDIT_ACCESS_REQUESTED: "EDIT_ACCESS_REQUESTED",
    AuditEventType.EDIT_ACCESS_APPROVED: "EDIT_ACCESS_APPROVED",
    AuditEventType.EDIT_ACCESS_REJECTED: "EDIT_ACCESS_REJECTED",
    AuditEventType.TICKET_CLOSED: "TICKET_CLOSED",
    AuditEventType.TICKET_REOPENED: "TICKET_REOPENED",
}

SYNTHESIZABLE_EVENT_TYPES = frozenset(_EVENT_TO_INTERACTION_TYPE.keys())


def _payload_for(log: AuditLog, interaction_type: str) -> dict:
    """
    Reconstructs exactly the payload keys lib/interactionMeta.ts's
    summarize() reads for this type, from the audit row's
    old_values/new_values — a pure JSON remap, not a re-derivation,
    since the write sites were widened to log everything synthesis
    needs (see interaction_service.py/edit_access_service.py).
    """

    old = log.old_values or {}
    new = log.new_values or {}

    if interaction_type == "STATUS_CHANGE":
        return {"from": old.get("current_status"), "to": new.get("current_status")}
    if interaction_type == "PRIORITY_CHANGE":
        return {"from": old.get("current_priority"), "to": new.get("current_priority")}
    if interaction_type == "AGENT_TRANSFER":
        return {
            "from_agent_id": old.get("agent_id"),
            "from_agent_name": old.get("agent_name"),
            "to_agent_id": new.get("agent_id"),
            "to_agent_name": new.get("agent_name"),
            "reason": new.get("reason"),
        }
    if interaction_type == "CLAIM":
        return {"agent_id": new.get("agent_id"), "agent_name": new.get("agent_name")}
    if interaction_type == "TICKET_CLOSED":
        return {
            "closed_by": new.get("closed_by"),
            "closed_by_name": new.get("closed_by_name"),
        }
    if interaction_type == "TICKET_REOPENED":
        return {}
    if interaction_type == "EDIT_ACCESS_REQUESTED":
        return {"request_id": new.get("request_id"), "reason": new.get("reason")}
    if interaction_type == "EDIT_ACCESS_REJECTED":
        # request_id was never part of this event's own new_values
        # (only requested_by/status/review_note are) — summarize()
        # only reads review_note for this type anyway, so it's
        # omitted here rather than always showing up as None.
        return {"review_note": new.get("review_note")}
    # EDIT_ACCESS_APPROVED — summarize() renders a fixed string
    # regardless of payload, no keys needed.
    return {}


def synthesize_interaction_from_audit(
    log: AuditLog,
    ticket_id: UUID,
    ticket_title: str,
    client_company_name: str | None = None,
) -> TicketInteractionResponse:
    """
    Builds a TicketInteractionResponse-shaped display row from one
    ticket_audit_logs row, for exactly the 9 retired event types that
    no longer have a real Interaction row of their own. Uses
    `log.audit_id` as the synthetic interaction_id — it's a real,
    unique UUID, just not one that exists in `interactions` (callers
    that key off interaction_id for actions like Hide must exclude
    these rows first, since a Hide call against one would 404).
    """

    interaction_type = _EVENT_TO_INTERACTION_TYPE[log.event_type]

    return TicketInteractionResponse(
        interaction_id=log.audit_id,
        ticket_id=ticket_id,
        interaction_type=interaction_type,
        status=InteractionStatus.ASSIGNED,
        direction=InteractionDirection.INTERNAL,
        performed_by=log.actor_id,
        performed_by_name=log.actor_name,
        subject=None,
        payload=_payload_for(log, interaction_type),
        is_visible=True,
        removed_by=None,
        removed_at=None,
        message_id=None,
        client_id=None,
        parent_interaction_id=None,
        received_at=None,
        created_at=log.created_at,
        attachments=[],
        conversation_id=None,
        in_reply_to_message_id=None,
        references=[],
        ticket_title=ticket_title,
        client_company_name=client_company_name,
    )
