from uuid import UUID

from pydantic import BaseModel


class AssignableUserSummary(BaseModel):
    """Just enough to render one row in the "Assigned To" picker."""

    user_id: UUID
    name: str
    # Official, human-readable Employee ID (e.g. "266") — display only,
    # never sent back to the server; the picker's selected *value*
    # remains user_id. None for accounts with no official employee
    # record (demo/system accounts).
    employee_number: str | None = None


class AssignableGroup(BaseModel):
    """One role-labeled section of the "Assigned To" picker (e.g. "Staff")."""

    role: str
    users: list[AssignableUserSummary]


class AssignableAgentsResponse(BaseModel):
    """
    Who the current user may assign a new ticket to when promoting an
    inbox email — always includes `me` (assigning to yourself), plus
    zero or more role-grouped hierarchies depending on the caller's own
    role (see AssignmentService.get_assignable_groups).
    """

    me: AssignableUserSummary
    groups: list[AssignableGroup]
