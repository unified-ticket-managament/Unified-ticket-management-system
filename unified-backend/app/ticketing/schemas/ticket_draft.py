from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field

#ticket_draft.py
#
# Ticket-scoped drafts — Save Draft for Ticket Reply and Internal Note
# (and Mail's own ticketed ReplyComposer, which sends through the same
# ticket-reply endpoints). A deliberate sibling to the pre-ticket Mail
# draft architecture (schemas/interaction.py's DraftSaveRequest/
# DraftResponse) rather than a shared shape — a ticket draft has no
# thread root to borrow context from (the ticket itself is the scope),
# and Reply/Internal-Note need genuinely different fields (recipients
# vs. addressed-to platform users), so each gets its own small request/
# response pair instead of one generic, mostly-optional shape.


class TicketReplyDraftSaveRequest(BaseModel):
    """
    Request body for creating/updating the current agent's draft
    Reply on a ticket. Every field is optional/defaulted — an entirely
    empty draft (just opened the Reply tab, nothing typed yet) is a
    valid save. Mirrors ReplyCreate's own recipient/body fields
    (ticket_action.py) minus anything only meaningful at send time
    (attachment_source_interaction_id, idempotency_key, reply_all).
    """

    to_email: EmailStr | None = None
    to_emails: list[EmailStr] = Field(default_factory=list)
    cc: list[EmailStr] = Field(default_factory=list)
    bcc: list[EmailStr] = Field(default_factory=list)
    message: str = ""
    body_html: str | None = None


class TicketReplyDraftResponse(BaseModel):
    interaction_id: UUID
    ticket_id: UUID
    to_email: str | None = None
    to_emails: list[str] = Field(default_factory=list)
    cc: list[str] = Field(default_factory=list)
    bcc: list[str] = Field(default_factory=list)
    message: str = ""
    body_html: str | None = None
    created_at: datetime


class TicketNoteDraftSaveRequest(BaseModel):
    """
    Request body for creating/updating the current agent's draft
    Internal Note on a ticket. `recipient_user_ids` mirrors
    InternalNoteCreate's own field exactly (note.py) — deliberately no
    email/free-text recipient field of any kind exists on this schema,
    which is what keeps a note draft internal-only by construction,
    the same guarantee the real send path already has.
    """

    subject: str = ""
    note: str = ""
    body_html: str | None = None
    recipient_user_ids: list[UUID] = Field(default_factory=list)


class TicketNoteDraftResponse(BaseModel):
    interaction_id: UUID
    ticket_id: UUID
    subject: str = ""
    note: str = ""
    body_html: str | None = None
    recipient_user_ids: list[UUID] = Field(default_factory=list)
    created_at: datetime
