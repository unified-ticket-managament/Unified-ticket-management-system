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


class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str


class UpdateProfileRequest(BaseModel):
    name: str | None = None
    email: EmailStr | None = None
    current_password: str | None = None
    password: str | None = None