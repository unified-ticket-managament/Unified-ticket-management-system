from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr


# -----------------------------
# Base Schema
# -----------------------------

class UserBase(BaseModel):
    name: str
    email: EmailStr
    role_id: UUID
    manager_id: UUID | None = None
    teamlead_id: UUID | None = None
    # Work-specialization category — required for Staff/Team Lead,
    # enforced in UserService.create_user (not here, since the
    # requirement depends on which role_id was chosen).
    category_id: UUID | None = None
    is_active: bool = True

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


# -----------------------------
# Update User
# -----------------------------

class UserUpdate(BaseModel):
    name: str | None = None
    email: EmailStr | None = None
    role_id: UUID | None = None
    manager_id: UUID | None = None
    teamlead_id: UUID | None = None
    category_id: UUID | None = None
    is_active: bool | None = None

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


# -----------------------------
# User Response
# -----------------------------

class UserResponse(UserBase):
    user_id: UUID
    created_at: datetime
    updated_at: datetime

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