from datetime import date
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshTokenRequest(BaseModel):
    refresh_token: str


class CurrentUser(BaseModel):
    user_id: UUID
    name: str
    email: EmailStr
    role: str
    role_id: UUID
    is_active: bool
    # Display-only Leave indicator, self-toggled from the Profile page
    # — see shared_models.models.User.is_on_leave's own docstring.
    is_on_leave: bool = False
    permissions: list[str]
    override_permissions: list[str] = []
    scoped_permissions: dict[str, list[str]] = {}

    # Official, human-readable Employee ID — see shared_models.models.
    # User's own docstring. Additive/optional so a client built before
    # this field existed keeps working unchanged.
    employee_number: str | None = None

    # Profile fields — see shared_models.models.User's own docstring.
    # All optional so this response shape stays backward compatible.
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

    # Per-user email signature, sanitized HTML — see
    # shared_models.models.User.signature_html's own docstring.
    signature_html: str | None = None

    # Mail Inbox panel widths (px) — see shared_models.models.User.
    # mail_inbox_folder_width/mail_inbox_list_width's own docstring.
    mail_inbox_folder_width: int | None = None
    mail_inbox_list_width: int | None = None


class MyPermissionItem(BaseModel):
    permission_id: UUID
    permission_name: str
    description: str | None = None
    granted: bool
    # "role" (granted via the caller's role defaults), "override"
    # (granted via a personal UserPermissionOverride), or "none".
    source: str
    scoped_ticket_ids: list[str] = []


class MyPermissionsResponse(BaseModel):
    user_id: UUID
    name: str
    email: EmailStr
    role: str
    permissions: list[MyPermissionItem]


class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str


class UpdateProfileRequest(BaseModel):
    name: str | None = None
    email: EmailStr | None = None
    current_password: str | None = None
    password: str | None = None

    # Self-toggled from the Profile page's own header — every role may
    # set their own leave status, regardless of whether they hold
    # user:update (which Staff does not by default).
    is_on_leave: bool | None = None

    # Self-service editable profile fields (see root CLAUDE.md's
    # Profile module section). `team`/role/user_id/reports-to are
    # deliberately not here — they stay read-only on the Profile page,
    # unaffected by this self-service endpoint.
    date_of_birth: date | None = None
    alternate_email: str | None = None
    phone_number: str | None = None
    office_location: str | None = None
    department: str | None = None
    language: str | None = None
    date_format: str | None = None
    time_format: str | None = None
    time_zone: str | None = None
    default_dashboard: str | None = None

    # Self-service signature editor — see shared_models.models.User.
    # signature_html's own docstring. Sanitized server-side
    # (AuthService.update_profile) before being persisted; capped here
    # rather than at the DB-column level since this string is
    # concatenated into every outbound email the user sends.
    signature_html: str | None = Field(default=None, max_length=20000)

    # Mail Inbox panel widths (px) — see shared_models.models.User.
    # mail_inbox_folder_width/mail_inbox_list_width's own docstring.
    # Lower bounds mirror MailWorkspaceLayout.tsx's own
    # FOLDER_MIN_WIDTH/LIST_MIN_WIDTH constants exactly; the upper
    # bound is a generous sanity ceiling, not a real layout constraint
    # (the frontend's own container-relative clamping/ResizeObserver
    # logic is what actually keeps a value sane for a given viewport —
    # this just rejects an obviously malformed/adversarial payload).
    mail_inbox_folder_width: int | None = Field(default=None, ge=180, le=4000)
    mail_inbox_list_width: int | None = Field(default=None, ge=240, le=4000)