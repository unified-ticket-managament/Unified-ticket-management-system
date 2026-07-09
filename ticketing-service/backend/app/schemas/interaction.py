from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from app.enums import InteractionDirection, InteractionStatus
from app.schemas.attachment import AttachmentMetadata
from app.schemas.common import ORMBase

#interaction.py
class InteractionCreate(BaseModel):
    ticket_id: UUID | None = None
    interaction_type: str = Field(..., min_length=1, max_length=50)
    status: InteractionStatus = InteractionStatus.PENDING
    direction: InteractionDirection
    performed_by: UUID | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    is_visible: bool = True
    message_id: str | None = Field(default=None, max_length=255)
    client_id: UUID | None = None
    parent_interaction_id: UUID | None = None
    received_at: datetime | None = None
    is_draft: bool = False
    conversation_id: str | None = Field(default=None, max_length=255)
    in_reply_to_message_id: str | None = Field(default=None, max_length=255)
    references: list[str] | None = None


class InteractionUpdate(BaseModel):
    ticket_id: UUID | None = None
    status: InteractionStatus | None = None
    payload: dict[str, Any] | None = None
    is_visible: bool | None = None
    removed_by: UUID | None = None
    removed_at: datetime | None = None


class InteractionResponse(ORMBase):
    interaction_id: UUID
    ticket_id: UUID | None
    interaction_type: str
    status: InteractionStatus
    direction: InteractionDirection
    performed_by: UUID | None
    performed_by_name: str | None = None
    payload: dict[str, Any]
    is_visible: bool
    removed_by: UUID | None
    removed_at: datetime | None
    message_id: str | None
    client_id: UUID | None = None
    parent_interaction_id: UUID | None = None
    received_at: datetime | None = None
    created_at: datetime
    attachments: list[AttachmentMetadata] = Field(default_factory=list)
    conversation_id: str | None = None
    in_reply_to_message_id: str | None = None
    references: list[str] = Field(default_factory=list)


class TicketInteractionResponse(InteractionResponse):
    """
    Same shape as InteractionResponse, with the owning ticket's title
    and client company name attached — used by the batched
    GET /tickets/interactions endpoint so the Interactions page
    doesn't have to fetch the ticket list and zip these on itself
    after fetching each ticket's timeline one at a time.
    """

    ticket_title: str
    client_company_name: str | None = None


class ThreadResponse(ORMBase):
    """
    A full conversation — the root (parent) interaction plus every
    reply/follow-up filed under it, chronologically ordered. Returned
    regardless of whether the caller asked for the root's own id or
    any reply/draft within the thread (the id is resolved up to the
    root first — see InteractionService.get_thread).
    """

    root: InteractionResponse
    replies: list[InteractionResponse] = Field(default_factory=list)
    reply_count: int = 0
    latest_reply: InteractionResponse | None = None


class HideInteractionRequest(BaseModel):
    """
    Request body for hiding (soft-deleting) an interaction.
    """

    removed_by: UUID | None = None


class HideInteractionResponse(ORMBase):
    """
    Response returned after an interaction has been
    hidden (soft-deleted) from the ticket timeline.
    """

    interaction_id: UUID
    ticket_id: UUID | None
    is_visible: bool
    removed_by: UUID | None
    removed_at: datetime | None
    message: str


class InteractionClaimResponse(ORMBase):
    """
    Response returned after a pending inbox item is claimed
    ("Assign to me").
    """

    interaction_id: UUID
    claimed_by: UUID | None
    claimed_by_name: str | None
    claimed_at: datetime | None
    message: str


class InteractionArchiveResponse(ORMBase):
    """
    Response returned after a pending inbox item is archived
    (the "Informational / Archive" reviewer decision).
    """

    interaction_id: UUID
    status: InteractionStatus
    message: str


class TagsUpdateRequest(BaseModel):
    """
    Full-replace tag list — the frontend always sends the complete
    set, there's no per-tag add/remove endpoint.
    """

    tags: list[str] = Field(default_factory=list)


class InteractionTagsResponse(ORMBase):
    interaction_id: UUID
    tags: list[str]
    message: str


class FolderAssignRequest(BaseModel):
    # None clears the folder assignment.
    folder_id: UUID | None = None


class InteractionFolderResponse(ORMBase):
    interaction_id: UUID
    folder_id: UUID | None
    message: str


class SnoozeRequest(BaseModel):
    snooze_until: datetime


class InteractionSnoozeResponse(ORMBase):
    interaction_id: UUID
    snoozed_until: datetime | None
    message: str


class DraftSaveRequest(BaseModel):
    message: str = Field(..., min_length=1)


class DraftResponse(ORMBase):
    """
    One agent's saved-but-unsent draft reply on a bare (pre-ticket)
    Mail thread. Upsert semantics — saving again on the same thread
    overwrites this same row, one active draft per thread per agent.
    """

    interaction_id: UUID
    root_interaction_id: UUID
    message: str
    created_at: datetime


class DraftDeleteResponse(BaseModel):
    message: str