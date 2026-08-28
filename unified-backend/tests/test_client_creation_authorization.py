# test_client_creation_authorization.py
#
# Phase 2C P0-3 fix: POST /clients (client.py's create_client route)
# previously had no backend authorization check at all — only
# get_current_agent (any authenticated agent role, including Staff/
# Team Lead). This file covers the added
# ensure_has_permission(current_user, "client:view") check, reusing
# the same permission GET /clients/{id}/details already gates via
# ensure_can_view_client_details — no new permission introduced, per
# Phase 2B's BD-14 discovery (zero live callers of this route existed
# before this fix, so no legitimate workflow is at risk).
#
# Same convention as the Phase 2A test files: route function called
# directly, real seeded users, `.permissions` set explicitly per test,
# everything inside a transaction that is always rolled back. Run this
# file individually (DB-touching test caveat).

import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import joinedload
from shared_models.models import Role, User

from app.database.session import AsyncSessionLocal, engine
from app.ticketing.api.client import create_client
from app.ticketing.repositories.client_repository import ClientRepository
from app.ticketing.schemas.client import ClientCreate


@pytest.fixture
async def db_session():
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.rollback()
    await engine.dispose()


async def _get_user_by_role(session, role_name: str) -> User:
    result = await session.execute(
        select(User)
        .options(joinedload(User.role))
        .join(Role, Role.role_id == User.role_id)
        .where(Role.name == role_name, User.is_active.is_(True))
    )
    users = result.unique().scalars().all()
    if users:
        return users[0]
    pytest.skip(f"No active seeded {role_name!r} found.")


def _throwaway_client_request(account_manager_id) -> ClientCreate:
    unique = uuid.uuid4().hex[:10]
    return ClientCreate(
        name=f"Throwaway Test Client {unique}",
        inbox_email=f"throwaway-client-{unique}@example.com",
        account_manager_id=account_manager_id,
    )


# ---------------------------------------------------------
# Regression: seed grants unchanged
# ---------------------------------------------------------


@pytest.mark.parametrize("role_name", ["Super Admin", "Site Lead", "Account Manager"])
async def test_role_holds_client_view(db_session, role_name):
    from app.rbac.repositories.role_permission_repository import RolePermissionRepository
    from app.rbac.repositories.role_repository import RoleRepository

    role = await RoleRepository(db_session).get_by_name(role_name)
    if role is None:
        pytest.skip(f"No {role_name!r} role seeded.")
    names = {
        p.permission_name
        for p in await RolePermissionRepository(db_session).get_permissions_by_role(role.role_id)
    }
    assert "client:view" in names


# ---------------------------------------------------------
# Positive: holding client:view succeeds
# ---------------------------------------------------------


@pytest.mark.parametrize("actor_role_name", ["Super Admin", "Site Lead", "Account Manager"])
async def test_actor_with_client_view_can_create_client(db_session, actor_role_name):
    actor = await _get_user_by_role(db_session, actor_role_name)
    actor.permissions = ["client:view"]

    account_manager = await _get_user_by_role(db_session, "Account Manager")
    request = _throwaway_client_request(account_manager.user_id)

    created = await create_client(request, current_user=actor, db=db_session)

    assert created.name == request.name
    stored = await ClientRepository(db_session).get_by_id(created.client_id)
    assert stored is not None
    assert stored.inbox_email == request.inbox_email.lower()


# ---------------------------------------------------------
# Negative: no client:view -> 403, and nothing is created
# ---------------------------------------------------------


@pytest.mark.parametrize("actor_role_name", ["Staff", "Team Lead"])
async def test_actor_without_client_view_is_denied(db_session, actor_role_name):
    actor = await _get_user_by_role(db_session, actor_role_name)
    actor.permissions = []

    account_manager = await _get_user_by_role(db_session, "Account Manager")
    request = _throwaway_client_request(account_manager.user_id)

    with pytest.raises(HTTPException) as exc_info:
        await create_client(request, current_user=actor, db=db_session)
    assert exc_info.value.status_code == 403

    stored = await ClientRepository(db_session).get_by_inbox_email(request.inbox_email.lower())
    assert stored is None


async def test_actor_with_unrelated_permission_is_still_denied(db_session):
    """Holding an unrelated permission (e.g. ticket:view_own) must not
    imply client:view — the two are deliberately separate grants."""

    actor = await _get_user_by_role(db_session, "Team Lead")
    actor.permissions = ["ticket:view_own", "communication:reply_external"]

    account_manager = await _get_user_by_role(db_session, "Account Manager")
    request = _throwaway_client_request(account_manager.user_id)

    with pytest.raises(HTTPException) as exc_info:
        await create_client(request, current_user=actor, db=db_session)
    assert exc_info.value.status_code == 403


# ---------------------------------------------------------
# Regression: existing business validation still runs, for an
# authorized actor — proves the new check is layered before existing
# logic, not in place of it.
# ---------------------------------------------------------


async def test_authorized_actor_still_blocked_by_duplicate_inbox_email(db_session):
    actor = await _get_user_by_role(db_session, "Super Admin")
    actor.permissions = ["client:view"]
    account_manager = await _get_user_by_role(db_session, "Account Manager")

    request = _throwaway_client_request(account_manager.user_id)
    await create_client(request, current_user=actor, db=db_session)

    # Same inbox_email again — pre-existing duplicate-email business
    # rule must still fire (400/409), not silently succeed.
    duplicate_request = ClientCreate(
        name="A different name",
        inbox_email=request.inbox_email,
        account_manager_id=account_manager.user_id,
    )
    with pytest.raises(HTTPException) as exc_info:
        await create_client(duplicate_request, current_user=actor, db=db_session)
    assert exc_info.value.status_code in (400, 409)


async def test_authorized_actor_still_blocked_by_invalid_account_manager(db_session):
    actor = await _get_user_by_role(db_session, "Site Lead")
    actor.permissions = ["client:view"]

    non_am = await _get_user_by_role(db_session, "Staff")
    request = _throwaway_client_request(non_am.user_id)

    with pytest.raises(HTTPException) as exc_info:
        await create_client(request, current_user=actor, db=db_session)
    assert exc_info.value.status_code == 400
