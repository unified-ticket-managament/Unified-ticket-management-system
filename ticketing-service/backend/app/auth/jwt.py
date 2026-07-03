# jwt.py
#
# Decode-only. This service never issues tokens — the RBAC service is the
# sole issuer (login/refresh). Ticketing trusts RBAC-issued access tokens
# by verifying them locally against the same JWT_SECRET_KEY, with no
# network call back to RBAC per request. Do not add create_access_token/
# create_refresh_token here.

from typing import Any

from jose import JWTError, jwt

from app.core.config import get_settings

settings = get_settings()


def decode_token(token: str) -> dict[str, Any]:
    try:
        return jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
        )
    except JWTError as exc:
        raise ValueError("Invalid or expired token.") from exc
