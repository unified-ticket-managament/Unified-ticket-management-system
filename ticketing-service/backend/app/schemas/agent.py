from uuid import UUID

from pydantic import BaseModel


class AgentSummaryResponse(BaseModel):
    """
    Minimal Staff-user info needed to populate agent pickers
    (e.g. the Transfer Agent dropdown) — sourced from the real
    `users` table, not hardcoded.
    """

    user_id: UUID
    name: str
    email: str
