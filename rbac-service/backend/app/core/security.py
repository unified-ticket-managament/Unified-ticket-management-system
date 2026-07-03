"""
Compatibility layer for authentication utilities.

Authentication logic is implemented inside the
app.auth package.

This module simply re-exports those functions so
existing imports continue to work.
"""

from app.auth.password import (
    get_password_hash,
    verify_password,
)

from app.auth.jwt import (
    create_access_token,
    create_refresh_token,
    decode_token,
)

__all__ = [
    "get_password_hash",
    "verify_password",
    "create_access_token",
    "create_refresh_token",
    "decode_token",
]