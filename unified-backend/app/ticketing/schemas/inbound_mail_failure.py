from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class InboundMailFailureResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    inbound_mail_failure_id: UUID
    message_id: str
    mailbox_address: str
    error_summary: str | None
    attempt_count: int
    first_seen_at: datetime
    last_seen_at: datetime
    resolved: bool


class InboundMailFailureListResponse(BaseModel):
    total: int
    items: list[InboundMailFailureResponse]
