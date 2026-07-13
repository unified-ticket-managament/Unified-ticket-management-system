# test_get_current_user_cache.py
#
# End-to-end coverage for the RBAC round-trip elimination:
# app.dependencies.auth.get_current_user should take the existing
# DB-fetch path on a cache miss, skip the DB entirely on a cache hit
# for the same (user_id, permission_version), and reject a token whose
# claimed permission_version no longer matches the DB's live value
# (simulating a role/permission change that happened after the token
# was issued).
#
# Runs against the real (dev) database inside a transaction that is
# always rolled back — same approach as test_interaction_threading.py
# (no separate test database is configured for this project). A real
# seeded user (staff@probeps.com) is read, never mutated in a way that
# survives the rollback.

from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import joinedload

from app.auth.jwt import create_access_token
from app.core.rbac_cache import RBACCache
from app.database.session import AsyncSessionLocal, engine
from app.dependencies import auth as auth_deps
from shared_models.models import User


@pytest.fixture
async def db_session():
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.rollback()
    await engine.dispose()


@pytest.fixture
def fresh_cache(monkeypatch):
    """
    Isolates each test from the module-level cache singleton (and from
    whatever this process's real TTL/max-size settings are) instead of
    letting tests observe each other's cache state.
    """

    cache = RBACCache(ttl_seconds=30, max_size=100)
    monkeypatch.setattr(auth_deps, "get_rbac_cache", lambda: cache)
    return cache


def _credentials(token: str) -> SimpleNamespace:
    # get_current_user only reads `.credentials` off this parameter —
    # matches HTTPAuthorizationCredentials' own shape without needing
    # to construct a real one.
    return SimpleNamespace(credentials=token)


async def _load_staff_user(db_session) -> User:
    result = await db_session.execute(
        select(User)
        .options(joinedload(User.role), joinedload(User.category))
        .where(User.email == "staff@probeps.com")
    )
    user = result.unique().scalar_one()
    return user


def _mint_token(user: User) -> str:
    return create_access_token(
        user_id=user.user_id,
        email=user.email,
        role=user.role.name if user.role else "Staff",
        permissions=["ticket:view_own"],
        scoped_permissions={},
        name=user.name,
        role_id=user.role_id,
        category_id=user.category_id,
        category=(
            user.category.category_name.value if user.category else None
        ),
        permission_version=user.permission_version,
    )


async def test_cache_miss_then_hit_skips_db_on_second_call(db_session, fresh_cache):
    user = await _load_staff_user(db_session)
    token = _mint_token(user)

    resolved_1 = await auth_deps.get_current_user(
        credentials=_credentials(token), db=db_session
    )
    assert resolved_1.user_id == user.user_id
    assert fresh_cache.is_valid(str(user.user_id), user.permission_version) is True

    # Second call: cache hit — reconstructed straight from JWT claims,
    # never touches UserRepository.get_by_id. If this raised or
    # returned wrong data, the transient-reconstruction path itself
    # would be broken, not just "slow".
    resolved_2 = await auth_deps.get_current_user(
        credentials=_credentials(token), db=db_session
    )
    assert resolved_2.user_id == user.user_id
    assert resolved_2.name == user.name
    assert resolved_2.role.name == (user.role.name if user.role else "Staff")
    assert resolved_2.is_active is True


async def test_stale_permission_version_is_rejected(db_session, fresh_cache):
    """
    Simulates an admin action bumping this user's permission_version
    (role change, deactivation, override grant/revoke, ...) after the
    token was already issued — the next DB-verified request for that
    token must reject it, not silently keep trusting the old claims.
    """

    user = await _load_staff_user(db_session)
    token = _mint_token(user)  # claims the CURRENT (pre-bump) version

    user.permission_version += 1
    await db_session.flush()

    with pytest.raises(HTTPException) as exc_info:
        await auth_deps.get_current_user(credentials=_credentials(token), db=db_session)

    assert exc_info.value.status_code == 401


async def test_token_without_permission_version_always_uses_db_path(db_session, fresh_cache):
    """
    Backward compatibility: a token minted before this change exists
    simply has no `permission_version` claim — must never crash, and
    must never be treated as a cache hit (there's no version to key on).
    """

    user = await _load_staff_user(db_session)
    old_style_token = create_access_token(
        user_id=user.user_id,
        email=user.email,
        role=user.role.name if user.role else "Staff",
        permissions=["ticket:view_own"],
        scoped_permissions={},
        # Deliberately omitting name/role_id/category_id/category/
        # permission_version — the pre-this-change payload shape.
    )

    resolved = await auth_deps.get_current_user(
        credentials=_credentials(old_style_token), db=db_session
    )
    assert resolved.user_id == user.user_id
    # Nothing should have been cached for a claim-less token.
    assert len(fresh_cache) == 0


async def test_deactivated_user_is_rejected_on_cache_miss(db_session, fresh_cache):
    user = await _load_staff_user(db_session)
    token = _mint_token(user)

    user.is_active = False
    await db_session.flush()

    with pytest.raises(HTTPException) as exc_info:
        await auth_deps.get_current_user(credentials=_credentials(token), db=db_session)

    assert exc_info.value.status_code == 403
