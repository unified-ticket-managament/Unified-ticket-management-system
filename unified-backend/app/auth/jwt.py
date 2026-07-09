from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from jose import JWTError, jwt

from app.core.config import get_settings

settings = get_settings()


class JWTManager:
    """
    Handles JWT Access Token and Refresh Token operations.

    RBAC remains the sole issuer by convention, not enforcement — ticketing
    code should only ever call `decode_token`, never `create_access_token`/
    `create_refresh_token`, even though this merge puts all three in one
    importable module. This mirrors the standalone ticketing-service
    backend's own `jwt.py`, which physically couldn't import a create_*
    function because none existed there.
    """

    @staticmethod
    def create_access_token(
        *,
        user_id: UUID,
        email: str,
        role: str,
        permissions: list[str],
        expires_delta: timedelta | None = None,
    ) -> str:

        expire = datetime.now(timezone.utc) + (
            expires_delta
            or timedelta(
                minutes=settings.access_token_expire_minutes
            )
        )

        payload: dict[str, Any] = {
            "sub": str(user_id),
            "user_id": str(user_id),
            "email": email,
            "role": role,
            "permissions": permissions,
            "type": "access",
            "exp": expire,
        }

        return jwt.encode(
            payload,
            settings.jwt_secret_key,
            algorithm=settings.jwt_algorithm,
        )

    @staticmethod
    def create_refresh_token(
        *,
        user_id: UUID,
        expires_delta: timedelta | None = None,
    ) -> str:

        expire = datetime.now(timezone.utc) + (
            expires_delta
            or timedelta(
                days=settings.refresh_token_expire_days
            )
        )

        payload: dict[str, Any] = {
            "sub": str(user_id),
            "user_id": str(user_id),
            "type": "refresh",
            "exp": expire,
        }

        return jwt.encode(
            payload,
            settings.jwt_secret_key,
            algorithm=settings.jwt_algorithm,
        )

    @staticmethod
    def decode_token(
        token: str,
    ) -> dict[str, Any]:

        try:
            return jwt.decode(
                token,
                settings.jwt_secret_key,
                algorithms=[settings.jwt_algorithm],
            )

        except JWTError as exc:
            raise ValueError("Invalid or expired token.") from exc


# --------------------------------------------------------------------
# Convenience Functions
# --------------------------------------------------------------------

create_access_token = JWTManager.create_access_token
create_refresh_token = JWTManager.create_refresh_token
decode_token = JWTManager.decode_token