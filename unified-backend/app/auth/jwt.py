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
        scoped_permissions: dict[str, list[str]] | None = None,
        name: str | None = None,
        role_id: UUID | None = None,
        category_id: UUID | None = None,
        category: str | None = None,
        permission_version: int | None = None,
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
            # Ticket-scoped grants (e.g. editother_ticket approved for
            # one specific ticket) — deliberately a separate claim from
            # `permissions` rather than folded into it, so a flat
            # membership check (has_permission) can never mistake "holds
            # this permission for exactly one ticket" for "holds it
            # everywhere". Optional/defaulted so a caller that hasn't
            # been updated yet still gets a valid token.
            "scoped_permissions": scoped_permissions or {},
            "type": "access",
            "exp": expire,
        }

        # Stable authorization claims added so ticketing's
        # get_current_user can build the request's User/Role/Category
        # context straight from the token on a cache hit, without a
        # Postgres round trip — see app/dependencies/auth.py and
        # app/core/rbac_cache.py. All optional/defaulted to None so a
        # caller that hasn't been updated yet (there is none today,
        # but keeps the signature backward-compatible) still mints a
        # valid token; a token missing these claims simply always
        # takes the DB-fetch path on decode, same as before this
        # change existed.
        if name is not None:
            payload["name"] = name
        if role_id is not None:
            payload["role_id"] = str(role_id)
        if category_id is not None:
            payload["category_id"] = str(category_id)
        if category is not None:
            payload["category"] = category
        if permission_version is not None:
            payload["permission_version"] = permission_version

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