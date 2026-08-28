# test_permission_catalog_authorization.py
#
# Phase 2A P0 fix: POST/PUT/DELETE /permissions previously had no
# backend authorization at all — only the two read routes (list/get)
# checked permission:view. This file covers the added
# ensure_has_permission(current_user, "permission:update") checks in
# app.rbac.api.v1.permissions (reusing the already-canonical
# "modify the permission system" gate, the same one PUT
# /roles/{id}/permissions already uses — no new permission introduced,
# per Phase 1's explicit design decision).
#
# Also covers the bundled Phase-0-discovered fix: deleting a
# permission now bumps permission_version for every user whose role
# held it, via the same bulk UPDATE
# UserRepository.bump_permission_version_for_role already provides —
# closing the gap where a deleted permission would otherwise remain
# live in an already-issued session for the rest of that token's
# natural lifetime.
#
# Same convention as test_user_delete_authorization.py: route
# functions called directly, real seeded users, `.permissions` set
# explicitly per test, everything inside a transaction that is always
# rolled back. Run this file individually (DB-touching test caveat).

import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import joinedload
from shared_models.models import Role, User

from app.database.session import AsyncSessionLocal, engine
from app.rbac.api.v1.permissions import (
    create_permission,
    delete_permission,
    get_permission,
    list_permissions,
    update_permission,
)
from app.rbac.repositories.permission_repository import PermissionRepository
from app.rbac.repositories.role_permission_repository import RolePermissionRepository
from app.rbac.repositories.role_repository import RoleRepository
from app.rbac.repositories.user_repository import UserRepository
from app.rbac.schemas.permission import PermissionCreate, PermissionUpdate
from app.rbac.services.permission_service import PermissionService


@pytest.fixture
async def db_session():
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.rollback()
    await engine.dispose()


def _build_permission_service(session) -> PermissionService:
    return PermissionService(
        permission_repository=PermissionRepository(session),
        role_permission_repository=RolePermissionRepository(session),
        user_repository=UserRepository(session),
    )


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


async def _get_role(session, role_name: str) -> Role:
    role = await RoleRepository(session).get_by_name(role_name)
    if role is None:
        pytest.skip(f"No {role_name!r} role seeded.")
    return role


def _throwaway_permission_name() -> str:
    return f"phase2a_test:throwaway_{uuid.uuid4().hex[:10]}"


# ---------------------------------------------------------
# Regression: seed grants unchanged
# ---------------------------------------------------------


async def test_super_admin_role_holds_permission_update(db_session):
    role = await _get_role(db_session, "Super Admin")
    names = {
        p.permission_name
        for p in await RolePermissionRepository(db_session).get_permissions_by_role(role.role_id)
    }
    assert "permission:update" in names


async def test_site_lead_role_holds_permission_update(db_session):
    role = await _get_role(db_session, "Site Lead")
    names = {
        p.permission_name
        for p in await RolePermissionRepository(db_session).get_permissions_by_role(role.role_id)
    }
    assert "permission:update" in names


# ---------------------------------------------------------
# Positive: holding permission:update can create/update/delete
# ---------------------------------------------------------


async def test_actor_with_permission_update_can_create(db_session):
    service = _build_permission_service(db_session)
    actor = await _get_user_by_role(db_session, "Super Admin")
    actor.permissions = ["permission:update"]

    name = _throwaway_permission_name()
    created = await create_permission(
        PermissionCreate(permission_name=name, description="Phase 2A regression test"),
        service=service,
        current_user=actor,
    )

    assert created.permission_name == name
    assert await PermissionRepository(db_session).get_by_name(name) is not None


async def test_actor_with_permission_update_can_update(db_session):
    service = _build_permission_service(db_session)
    actor = await _get_user_by_role(db_session, "Super Admin")
    actor.permissions = ["permission:update"]

    name = _throwaway_permission_name()
    created = await create_permission(
        PermissionCreate(permission_name=name, description="original"),
        service=service,
        current_user=actor,
    )

    updated = await update_permission(
        created.permission_id,
        PermissionUpdate(description="updated by test"),
        service=service,
        current_user=actor,
    )

    assert updated.description == "updated by test"


async def test_actor_with_permission_update_can_delete(db_session):
    service = _build_permission_service(db_session)
    actor = await _get_user_by_role(db_session, "Super Admin")
    actor.permissions = ["permission:update"]

    name = _throwaway_permission_name()
    created = await create_permission(
        PermissionCreate(permission_name=name, description="to be deleted"),
        service=service,
        current_user=actor,
    )

    await delete_permission(created.permission_id, service=service, current_user=actor)

    assert await PermissionRepository(db_session).get_by_id(created.permission_id) is None


# ---------------------------------------------------------
# Negative: no permission:update -> 403, and nothing mutates
# ---------------------------------------------------------


@pytest.mark.parametrize("actor_role_name", ["Account Manager", "Team Lead", "Staff"])
async def test_actor_without_permission_update_cannot_create(db_session, actor_role_name):
    service = _build_permission_service(db_session)
    actor = await _get_user_by_role(db_session, actor_role_name)
    actor.permissions = []

    name = _throwaway_permission_name()
    with pytest.raises(HTTPException) as exc_info:
        await create_permission(
            PermissionCreate(permission_name=name, description="should not be created"),
            service=service,
            current_user=actor,
        )
    assert exc_info.value.status_code == 403
    assert await PermissionRepository(db_session).get_by_name(name) is None


async def test_permission_view_only_actor_cannot_mutate_catalog(db_session):
    """The single most important negative case: permission:view alone
    (view-only administrative access) must not imply permission:update
    (mutation access) — these are deliberately separate grants."""

    service = _build_permission_service(db_session)
    actor = await _get_user_by_role(db_session, "Team Lead")
    actor.permissions = ["permission:view"]

    name = _throwaway_permission_name()
    with pytest.raises(HTTPException) as exc_info:
        await create_permission(
            PermissionCreate(permission_name=name, description="should not be created"),
            service=service,
            current_user=actor,
        )
    assert exc_info.value.status_code == 403

    # And update/delete on an existing (real, already-seeded) permission
    # are equally denied — resolved by name rather than hand-picking an
    # id, so this stays correct regardless of seed data specifics.
    existing = await PermissionRepository(db_session).get_by_name("permission:view")
    assert existing is not None

    with pytest.raises(HTTPException) as exc_info:
        await update_permission(
            existing.permission_id,
            PermissionUpdate(description="should not change"),
            service=service,
            current_user=actor,
        )
    assert exc_info.value.status_code == 403

    with pytest.raises(HTTPException) as exc_info:
        await delete_permission(existing.permission_id, service=service, current_user=actor)
    assert exc_info.value.status_code == 403


# ---------------------------------------------------------
# Regression: existing read behavior (list/get) is completely
# unaffected — still gated by permission:view alone, as before.
# ---------------------------------------------------------


async def test_permission_view_actor_can_still_list_and_get(db_session):
    service = _build_permission_service(db_session)
    actor = await _get_user_by_role(db_session, "Team Lead")
    actor.permissions = ["permission:view"]

    listing = await list_permissions(page=1, page_size=10, service=service, current_user=actor)
    assert listing.total > 0

    existing = await PermissionRepository(db_session).get_by_name("permission:view")
    fetched = await get_permission(existing.permission_id, service=service, current_user=actor)
    assert fetched.permission_name == "permission:view"


async def test_actor_without_permission_view_still_denied_read(db_session):
    """Confirms this fix didn't accidentally touch the pre-existing
    read gate at all — list/get should reject exactly as before."""

    service = _build_permission_service(db_session)
    actor = await _get_user_by_role(db_session, "Staff")
    actor.permissions = []

    with pytest.raises(HTTPException) as exc_info:
        await list_permissions(page=1, page_size=10, service=service, current_user=actor)
    assert exc_info.value.status_code == 403


# ---------------------------------------------------------
# permission_version cache-invalidation fix
# ---------------------------------------------------------


async def test_deleting_permission_bumps_permission_version_for_holders(db_session):
    service = _build_permission_service(db_session)
    actor = await _get_user_by_role(db_session, "Super Admin")
    actor.permissions = ["permission:update"]

    staff_role = await _get_role(db_session, "Staff")
    staff_user = await _get_user_by_role(db_session, "Staff")
    version_before = staff_user.permission_version

    name = _throwaway_permission_name()
    created = await create_permission(
        PermissionCreate(permission_name=name, description="cache-bump regression test"),
        service=service,
        current_user=actor,
    )

    # Grant it directly to Staff — deliberately bypassing
    # RolePermissionService here so this test isolates
    # delete_permission's own fix rather than also exercising the
    # already-covered assign path.
    await RolePermissionRepository(db_session).assign_permission(
        staff_role.role_id, created.permission_id
    )
    await db_session.flush()

    await delete_permission(created.permission_id, service=service, current_user=actor)

    await db_session.refresh(staff_user)
    assert staff_user.permission_version == version_before + 1


async def test_deleting_permission_with_no_role_holders_touches_no_one(db_session):
    """A permission nobody currently holds (e.g. one of Phase 0's
    dead/unused catalog entries) must not bump anyone's version —
    confirms the fix is targeted, not a blanket invalidation."""

    service = _build_permission_service(db_session)
    actor = await _get_user_by_role(db_session, "Super Admin")
    actor.permissions = ["permission:update"]

    staff_user = await _get_user_by_role(db_session, "Staff")
    version_before = staff_user.permission_version

    name = _throwaway_permission_name()
    created = await create_permission(
        PermissionCreate(permission_name=name, description="never assigned to any role"),
        service=service,
        current_user=actor,
    )

    await delete_permission(created.permission_id, service=service, current_user=actor)

    await db_session.refresh(staff_user)
    assert staff_user.permission_version == version_before
