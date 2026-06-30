from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from app.enums import InteractionStatus


class OpenEmailResponse(BaseModel):
    """
    Response returned when an agent opens
    an email from the inbox.
    """

    interaction_id: UUID

    client_name: str

    agent_name: str

    from_email: str

    subject: str

    body: str

    message_id: str | None

    received_at: datetime

    status: InteractionStatus