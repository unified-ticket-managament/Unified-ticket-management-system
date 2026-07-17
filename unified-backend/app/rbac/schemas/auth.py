from datetime import date
from uuid import UUID

from pydantic import BaseModel, EmailStr


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
    permissions: list[str]
    override_permissions: list[str] = []
    scoped_permissions: dict[str, list[str]] = {}

    # Profile fields — see shared_models.models.User's own docstring.
    # All optional so this response shape stays backward compatible.
    date_of_birth: date | None = None
    alternate_email: str | None = None
    phone_number: str | None = None
    office_location: str | None = None
    department: str | None = None
    team: str | None = None
    language: str | None = None
    date_format: str | None = None
    time_format: str | None = None
    time_zone: str | None = None
    default_dashboard: str | None = None


class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str


class UpdateProfileRequest(BaseModel):
    name: str | None = None
    email: EmailStr | None = None
    current_password: str | None = None
    password: str | None = None

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