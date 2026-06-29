from datetime import datetime
from typing import Generic, TypeVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field

T = TypeVar("T")


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class PaginatedResponse(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    page_size: int
    total_pages: int


class MessageResponse(BaseModel):
    message: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class RefreshTokenRequest(BaseModel):
    refresh_token: str


class UserBase(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    email: EmailStr
    role_id: UUID
    is_active: bool = True


class UserCreate(UserBase):
    password: str = Field(min_length=8, max_length=128)


class UserUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    email: EmailStr | None = None
    role_id: UUID | None = None
    is_active: bool | None = None
    password: str | None = Field(default=None, min_length=8, max_length=128)


class RoleSummary(ORMModel):
    id: UUID
    name: str


class UserResponse(ORMModel):
    id: UUID
    name: str
    email: str
    role_id: UUID
    is_active: bool
    created_at: datetime
    updated_at: datetime
    role: RoleSummary | None = None


class ProfileUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    email: EmailStr | None = None
    password: str | None = Field(default=None, min_length=8, max_length=128)
    current_password: str | None = Field(default=None, min_length=8, max_length=128)


class RoleBase(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str | None = None


class RoleCreate(RoleBase):
    pass


class RoleUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = None


class RoleResponse(ORMModel):
    id: UUID
    name: str
    description: str | None
    created_at: datetime


class PermissionResponse(ORMModel):
    id: UUID
    permission_name: str
    description: str | None


class RolePermissionsUpdate(BaseModel):
    permission_ids: list[UUID]


class AuditLogResponse(ORMModel):
    id: UUID
    user_id: UUID | None
    action: str
    entity_type: str
    entity_id: str | None
    old_value: str | None
    new_value: str | None
    timestamp: datetime


class AuthMeResponse(ORMModel):
    id: UUID
    name: str
    email: str
    role: str
    role_id: UUID
    permissions: list[str]
    is_active: bool
