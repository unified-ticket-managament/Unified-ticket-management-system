# test_permission_override_direct_am_staff.py
#
# Regression coverage for the "direct AM -> Staff reporting" fix:
#
#   - OrganizationService._build_subtree (and its flattened form,
#     get_subordinate_user_ids) used to resolve an Account Manager's
#     subordinates only via the Team-Lead-role tier
#     (get_by_manager_and_role(am_id, team_lead_role_id)) — a Staff
#     member whose manager_id pointed straight at the AM, with no Team
#     Lead in between, was silently invisible to this traversal even
#     though that's a valid, real organizational shape (see root
#     CLAUDE.md's "Organization Structure" section). This blocked
#     PermissionOverrideService.ensure_can_manage_overrides (and, by
#     extension, PermissionRequestService, which reuses it) from ever
#     letting that AM manage that Staff member's permission overrides.
#   - Fixed by also fetching Staff whose manager_id is the AM, unioned
#     with the existing Team-Lead-mediated set.
#
# No hardcoded user/category ids: every fixture here is a throwaway
# row created inside this test's own rolled-back transaction, and role
# ids are looked up by name against whatever roles are actually seeded
# — never assumed to be a specific id.
#
# Runs against the real (dev) database inside a transaction that is
# always rolled back at the end — same convention as
# test_user_listing_hierarchy.py. Per this repo's own documented
# pytest-asyncio caveat, run this file individually if the full DB-
# touching suite misbehaves.

import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import joinedload, selectinload
from shared_models.models import Role, User

from app.database.session import AsyncSessionLocal, engine
from app.rbac.repositories.audit_log_repository import AuditLogRepository
from app.rbac.repositories.permission_override_repository import (
    PermissionOverrideRepository,
)
from app.rbac.repositories.permission_repository import PermissionRepository
from app.rbac.repositories.reporting_manager_repository import ReportingManagerRepository
from app.rbac.repositories.role_permission_repository import RolePermissionRepository
from app.rbac.repositories.role_repository import RoleRepository
from app.rbac.repositories.user_repository import UserRepository
from app.rbac.services.audit_log_service import AuditLogService
from app.rbac.services.organization_service import OrganizationService
from app.rbac.services.permission_override_service import PermissionOverrideService
from app.rbac.services.permission_resolver import PermissionResolverService


@pytest.fixture
async def db_session():
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.rollback()
    await engine.dispose()


def _build_organization_service(session) -> OrganizationService:
    return OrganizationService(
        user_repository=UserRepository(session),
        role_repository=RoleRepository(session),
        reporting_manager_repository=ReportingManagerRepository(session),
    )


def _build_override_service(session, organization_service) -> PermissionOverrideService:
    return PermissionOverrideService(
        user_repository=UserRepository(session),
        permission_repository=PermissionRepository(session),
        permission_override_repository=PermissionOverrideRepository(session),
        organization_service=organization_service,
        permission_resolver=PermissionResolverService(
            role_permission_repository=RolePermissionRepository(session),
            permission_override_repository=PermissionOverrideRepository(session),
        ),
        audit_log_service=AuditLogService(audit_log_repository=AuditLogRepository(session)),
    )


async def _get_role(session, role_name: str) -> Role:
    role = await RoleRepository(session).get_by_name(role_name)
    if role is None:
        pytest.skip(f"Role {role_name!r} not seeded in this database.")
    return role


async def _make_user(session, *, name: str, role: Role, manager_id=None, teamlead_id=None) -> User:
    user = User(
        user_id=uuid.uuid4(),
        name=name,
        email=f"{name.lower().replace(' ', '.')}-{uuid.uuid4().hex[:8]}@example.test",
        password_hash="not-a-real-hash",
        role_id=role.role_id,
        manager_id=manager_id,
        teamlead_id=teamlead_id,
        is_active=True,
    )
    session.add(user)
    await session.flush()
    # Reload with .role/.category/.categories eager-loaded — every
    # helper under test reads user.role.name directly, and
    # OrganizationService._to_node reads user.categories for every
    # node it builds (production repository methods like
    # get_by_manager_and_role already selectinload this; a throwaway
    # row built here must match or _to_node's lazy access raises
    # MissingGreenlet under the async session).
    result = await session.execute(
        select(User)
        .options(
            joinedload(User.role),
            selectinload(User.category),
            selectinload(User.categories),
        )
        .where(User.user_id == user.user_id)
    )
    return result.unique().scalar_one()


@pytest.fixture
async def org_fixture(db_session):
    """
    AM
    +-- Team Lead -> Staff (via_tl)     Team-Lead-mediated report
    +-- Staff (direct)                  reports straight to the AM
    Unrelated AM -> Unrelated Staff     outside the first AM's tree
    """

    am_role = await _get_role(db_session, "Account Manager")
    tl_role = await _get_role(db_session, "Team Lead")
    staff_role = await _get_role(db_session, "Staff")

    am = await _make_user(db_session, name="Test AM Root", role=am_role)
    team_lead = await _make_user(db_session, name="Test TL", role=tl_role, manager_id=am.user_id)
    staff_via_tl = await _make_user(
        db_session, name="Test Staff Via TL", role=staff_role, teamlead_id=team_lead.user_id
    )
    staff_direct = await _make_user(
        db_session, name="Test Staff Direct", role=staff_role, manager_id=am.user_id
    )

    other_am = await _make_user(db_session, name="Test Other AM", role=am_role)
    unrelated_staff = await _make_user(
        db_session, name="Test Unrelated Staff", role=staff_role, manager_id=other_am.user_id
    )

    return {
        "am": am,
        "team_lead": team_lead,
        "staff_via_tl": staff_via_tl,
        "staff_direct": staff_direct,
        "unrelated_staff": unrelated_staff,
    }


async def test_subordinate_ids_include_both_team_lead_mediated_and_direct_staff(
    db_session, org_fixture
):
    service = _build_organization_service(db_session)
    subordinate_ids = await service.get_subordinate_user_ids(org_fixture["am"])

    assert org_fixture["team_lead"].user_id in subordinate_ids
    assert org_fixture["staff_via_tl"].user_id in subordinate_ids
    assert org_fixture["staff_direct"].user_id in subordinate_ids
    assert org_fixture["unrelated_staff"].user_id not in subordinate_ids


async def test_am_can_manage_overrides_for_team_lead_mediated_staff(db_session, org_fixture):
    organization_service = _build_organization_service(db_session)
    service = _build_override_service(db_session, organization_service)

    # Must not raise.
    await service.ensure_can_manage_overrides(org_fixture["am"], org_fixture["staff_via_tl"])


async def test_am_can_manage_overrides_for_direct_staff_report(db_session, org_fixture):
    """
    The core bug this fix addresses: a Staff member reporting straight
    to the AM (no Team Lead in between) must be manageable too.
    """

    organization_service = _build_organization_service(db_session)
    service = _build_override_service(db_session, organization_service)

    # Must not raise.
    await service.ensure_can_manage_overrides(org_fixture["am"], org_fixture["staff_direct"])


async def test_am_cannot_manage_overrides_for_unrelated_staff(db_session, org_fixture):
    organization_service = _build_organization_service(db_session)
    service = _build_override_service(db_session, organization_service)

    with pytest.raises(HTTPException) as exc_info:
        await service.ensure_can_manage_overrides(org_fixture["am"], org_fixture["unrelated_staff"])
    assert exc_info.value.status_code == 403


async def test_non_authorized_actor_cannot_manage_overrides(db_session, org_fixture):
    """
    A Team Lead holds no permission:override_grant by default — denied
    outright, regardless of any reporting relationship.
    """

    organization_service = _build_organization_service(db_session)
    service = _build_override_service(db_session, organization_service)

    with pytest.raises(HTTPException) as exc_info:
        await service.ensure_can_manage_overrides(
            org_fixture["team_lead"], org_fixture["staff_via_tl"]
        )
    assert exc_info.value.status_code == 403
