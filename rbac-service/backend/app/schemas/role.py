from uuid import UUID

from pydantic import BaseModel

from app.schemas.common import ORMBase


# --------------------------------------------------
# Base Schema
# --------------------------------------------------


class RoleBase(BaseModel):
    name: str


# --------------------------------------------------
# Create Role
# --------------------------------------------------


class RoleCreate(RoleBase):
    pass


# --------------------------------------------------
# Update Role
# --------------------------------------------------


class RoleUpdate(BaseModel):
    name: str | None = None


# --------------------------------------------------
# Role Response
# --------------------------------------------------


class RoleResponse(ORMBase):
    role_id: UUID
    name: str


# --------------------------------------------------
# Role List Response
# --------------------------------------------------

class RoleListResponse(BaseModel):
    roles: list[RoleResponse]
    total: int