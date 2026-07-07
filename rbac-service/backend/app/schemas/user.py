from datetime import datetime
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