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
    # Display-only Leave indicator — see shared_models.models.User.
    # is_on_leave's own docstring. Never narrows/reorders this picker;
    # the frontend appends "(Leave)" to the label when true.
    is_on_leave: bool = False


class AssignableGroup(BaseModel):
    """One role-labeled section of the "Assigned To" picker (e.g. "Staff")."""

    role: str
    users: list[AssignableUserSummary]


class AssignableAgentsResponse(BaseModel):
    """
    Who the current user may assign a new ticket to when promoting an
    inbox email — usually includes `me` (assigning to yourself), plus
    zero or more role-grouped hierarchies depending on the caller's own
    role (see AssignmentService.get_assignable_groups). `me` is `None`
    only for EscalationService.get_acknowledge_candidates' one
    exception: a Reporting-Manager-tagged escalation owner may not
    assign the ticket to themselves (see that method's own docstring) —
    every other caller of this schema (AssignmentService.
    get_assignable_groups, InteractionService.get_transfer_candidates)
    still always returns a real value.
    """

    me: AssignableUserSummary | None = None
    groups: list[AssignableGroup]
