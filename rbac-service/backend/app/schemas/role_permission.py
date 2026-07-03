from uuid import UUID

from pydantic import BaseModel


# --------------------------------------------------
# Assign / Replace Permissions Request
# --------------------------------------------------


class AssignPermissionsRequest(BaseModel):
    permission_ids: list[UUID]
