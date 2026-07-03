from uuid import UUID

from pydantic import BaseModel


# --------------------------------------------------
# Organization Chart Node
# --------------------------------------------------


class OrganizationNode(BaseModel):
    user_id: UUID
    name: str
    email: str
    role: str
    department: str | None = None
    is_active: bool
    children: list["OrganizationNode"] = []


OrganizationNode.model_rebuild()
