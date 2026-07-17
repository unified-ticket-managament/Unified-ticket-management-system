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
    # How this node relates to its rendered parent in the chart:
    # "reports_to" (the real manager_id/teamlead_id reporting line),
    # "reporting_manager" (an Account Manager's Reporting Manager
    # responsibility over this Team Lead's category — see root
    # CLAUDE.md's "Organization Structure" section), or "assignable"
    # (neither of the above — just the unrestricted, company-wide
    # ticket-assignment relationship every Account Manager has with
    # every Team Lead, shown only as part of that Account Manager's
    # own downward expansion, never as an ancestor fan-out for
    # someone else's chart). Lets the frontend render all three
    # differently instead of implying a false reporting relationship.
    relationship_to_parent: str = "reports_to"
    # Category names this node (an Account Manager) is the Reporting
    # Manager for — always empty for every other role. Purely
    # additional/display data; never used to compute `children` for
    # non-Account-Manager nodes.
    reporting_manager_for: list[str] = []
    children: list["OrganizationNode"] = []


OrganizationNode.model_rebuild()
