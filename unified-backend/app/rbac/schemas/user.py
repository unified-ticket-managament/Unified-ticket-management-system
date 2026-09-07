from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field


# -----------------------------
# Base Schema
# -----------------------------

class UserBase(BaseModel):
    name: str
    email: EmailStr
    role_id: UUID
    manager_id: UUID | None = None
    teamlead_id: UUID | None = None
    # Organization-Chart-only reporting relationship — separate from
    # manager_id/teamlead_id above, which keep their existing meaning
    # and every existing consumer unchanged. Unrestricted by role; see
    # OrganizationService's own docstring.
    reporting_manager_id: UUID | None = None
    # Work-specialization category — required for Staff/Team Lead,
    # enforced in UserService.create_user (not here, since the
    # requirement depends on which role_id was chosen). Kept as a
    # "legacy primary category" — see `category_ids` below, the new
    # multi-category-aware field. Both may be sent together as long as
    # they agree (`category_id == category_ids[0]`); see
    # UserService._resolve_category_ids.
    category_id: UUID | None = None

    # Full set of categories this user belongs to (many-to-many, via
    # the `user_categories` join table) — a user (most commonly a Team
    # Lead) may belong to more than one. Additive alongside
    # `category_id` above, never a replacement for it.
    category_ids: list[UUID] = Field(default_factory=list)
    is_active: bool = True
    # Display-only Leave indicator (see shared_models.models.User.
    # is_on_leave's own docstring) — never an authorization/eligibility
    # rule, purely surfaced as "(Leave)" wherever a user picker renders.
    is_on_leave: bool = False

    # The official, human-readable Employee ID (e.g. "266") — see
    # shared_models.models.User's own docstring. Purely additional to
    # user_id (UUID), never a relational key.
    employee_number: str | None = None

    # -----------------------------
    # Profile fields — see shared_models.models.User's own docstring
    # for why department/team are deliberately independent of
    # category_id above.
    # -----------------------------
    date_of_birth: date | None = None
    alternate_email: str | None = None
    phone_number: str | None = None
    office_location: str | None = None
    department: str | None = None
    team: str | None = None
    designation: str | None = None
    language: str | None = None
    date_format: str | None = None
    time_format: str | None = None
    time_zone: str | None = None
    default_dashboard: str | None = None


# -----------------------------
# Create User
# -----------------------------

class UserCreate(UserBase):
    password: str

    # Client role only — at least one is required (validated in
    # UserService, since a fixed Field(min_length=1) here would also
    # apply to every non-Client role's always-None default). Ignored
    # for every other role.
    contact_emails: list[EmailStr] | None = None


# -----------------------------
# Update User
# -----------------------------

class UserUpdate(BaseModel):
    name: str | None = None
    email: EmailStr | None = None
    role_id: UUID | None = None
    manager_id: UUID | None = None
    teamlead_id: UUID | None = None
    reporting_manager_id: UUID | None = None
    category_id: UUID | None = None
    category_ids: list[UUID] | None = None
    is_active: bool | None = None
    is_on_leave: bool | None = None
    employee_number: str | None = None

    date_of_birth: date | None = None
    alternate_email: str | None = None
    phone_number: str | None = None
    office_location: str | None = None
    department: str | None = None
    team: str | None = None
    designation: str | None = None
    language: str | None = None
    date_format: str | None = None
    time_format: str | None = None
    time_zone: str | None = None
    default_dashboard: str | None = None

    # Client role only — full-replace semantics (see
    # ClientRepository.set_contacts). Omit entirely to leave a
    # Client's existing contacts untouched.
    contact_emails: list[EmailStr] | None = None


# Admin-initiated password reset (RBAC Enforcement Audit, Phase 23) —
# distinct from AuthService's self-service ChangePasswordRequest
# (which requires the caller's own old_password). This is used only by
# an authorized administrator resetting another user's password
# (user:reset_password, see users.py's reset_password route) — no
# old_password field, since the actor is not the account owner.
class AdminPasswordReset(BaseModel):
    new_password: str = Field(min_length=8)


# -----------------------------
# Reset Password (Super Admin / user:reset_password only)
# -----------------------------

class ResetPasswordRequest(BaseModel):
    new_password: str = Field(min_length=8)


# -----------------------------
# User Response
# -----------------------------

class UserResponse(UserBase):
    user_id: UUID
    created_at: datetime
    updated_at: datetime

    # Computed, read-only: does this user hold at least one active
    # reporting_manager_teams assignment (any category) — i.e. are
    # they a Reporting Manager at all. This is an HR responsibility
    # layered on top of the Account Manager role, not a Role/
    # permission of its own — see OrganizationService.
    # get_reporting_manager_user_ids, the sole computer of this field.
    # Backs the Users page's "Reporting Manager" option in its Role
    # filter dropdown. Deliberately on UserResponse only, not
    # UserBase — UserCreate/UserUpdate also extend UserBase and this
    # must never be a client-settable field.
    is_reporting_manager: bool = False

    model_config = ConfigDict(from_attributes=True)


# -----------------------------
# User Summary
# -----------------------------

class UserSummary(BaseModel):
    user_id: UUID
    name: str
    email: EmailStr

    model_config = ConfigDict(from_attributes=True)


# -----------------------------
# User List Response
# -----------------------------

class UserListResponse(BaseModel):
    users: list[UserResponse]
    total: int