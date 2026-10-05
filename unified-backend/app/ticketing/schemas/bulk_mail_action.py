from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from app.ticketing.enums import TicketPriority

BULK_MAX_INTERACTIONS = 100

BulkMailActionName = Literal[
    "mark_read",
    "mark_unread",
    "archive",
    "move",
    "delete",
    # Trash -> Restore: undoes "delete".
    "restore",
    # Personal Flag / Pin (MessageMarkService).
    "flag",
    "unflag",
    "pin",
    "unpin",
    "create_ticket",
    # link_ticket and attach_to_ticket are aliases for the one existing
    # "attach interaction to existing ticket" workflow.
    "link_ticket",
    "attach_to_ticket",
]

TICKET_TARGET_ACTIONS = {"link_ticket", "attach_to_ticket"}


class BulkMailActionRequest(BaseModel):
    """
    One action applied independently to each selected interaction.
    Every interaction is authorized and processed on its own — see
    BulkMailActionService.
    """

    interaction_ids: list[UUID] = Field(..., min_length=1, max_length=BULK_MAX_INTERACTIONS)
    action: BulkMailActionName

    # move — None unfiles, same as FolderAssignRequest.
    folder_id: UUID | None = None

    # link_ticket / attach_to_ticket
    ticket_id: UUID | None = None
    # Only applied by the existing attach workflow when the target
    # ticket is CLOSED (reopen).
    new_agent_id: UUID | None = None
    new_priority: TicketPriority | None = None

    # create_ticket — one ticket per interaction; the title is each
    # email's own subject.
    ticket_type: str | None = Field(default=None, min_length=1, max_length=100)
    current_priority: TicketPriority = TicketPriority.MEDIUM
    agent_id: UUID | None = None

    @model_validator(mode="after")
    def _check_action_fields(self):
        if self.action in TICKET_TARGET_ACTIONS and self.ticket_id is None:
            raise ValueError("ticket_id is required for this action.")
        if self.action == "create_ticket" and not self.ticket_type:
            raise ValueError("ticket_type is required for create_ticket.")
        return self


class BulkMailActionItemResult(BaseModel):
    interaction_id: UUID
    status: Literal["success", "failed", "skipped"]
    reason: str | None = None
    # create_ticket / attach: the ticket the item ended up on.
    ticket_id: UUID | None = None


class BulkMailActionResponse(BaseModel):
    requested: int
    succeeded: int
    failed: int
    skipped: int = 0
    results: list[BulkMailActionItemResult]
