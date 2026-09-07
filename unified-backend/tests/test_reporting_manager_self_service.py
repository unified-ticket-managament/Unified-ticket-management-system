# test_reporting_manager_self_service.py
#
# Coverage for the Account Manager self-service fix on the Reporting
# Manager <-> Category mapping:
#
#   - `org:manage_reporting_managers` remains the broad administrative
#     permission (Super Admin/Site Lead by default) that can manage
#     ANY Account Manager's mapping — unchanged (Option B: kept, not
#     removed — see root CLAUDE.md's "Organization Structure" section
#     and this fix's own plan).
#   - New: an Account Manager without that permission may now manage
#     their OWN mapping (assign/revoke/list), authorized purely by
#     `actor.user_id == target_account_manager_id` — never a
#     hardcoded id/name/email. Managing another AM's mapping is still
#     denied.
#
# Runs against the real (dev) database inside a transaction that is
# always rolled back at the end. Run this file individually per this
# repo's own documented pytest-asyncio DB-touching-file caveat.

import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import joinedload, selectinload
from shared_models.models import Category, Role, User

from app.database.session import AsyncSessionLocal, engine
from app.rbac.repositories.audit_log_repository import AuditLogRepository
from app.rbac.repositories.category_repository import CategoryRepository
from app.rbac.repositories.reporting_manager_repository import ReportingManagerRepository
from app.rbac.repositories.role_repository import RoleRepository
from app.rbac.repositories.user_repository import UserRepository
from app.rbac.schemas.reporting_manager import ReportingManagerAssign
from app.rbac.services.audit_log_service import AuditLogService
from app.rbac.services.reporting_manager_service import ReportingManagerService


@pytest.fixture
async def db_session():
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.rollback()
    await engine.dispose()


def _build_service(session) -> ReportingManagerService:
    return ReportingManagerService(
        reporting_manager_repository=ReportingManagerRepository(session),
        user_repository=UserRepository(session),
        category_repository=CategoryRepository(session),
        audit_log_service=AuditLogService(audit_log_repository=AuditLogRepository(session)),
    )


async def _get_role(session, role_name: str) -> Role:
    role = await RoleRepository(session).get_by_name(role_name)
    if role is None:
        pytest.skip(f"Role {role_name!r} not seeded in this database.")
    return role


async def _make_user(session, *, name: str, role: Role) -> User:
    user = User(
        user_id=uuid.uuid4(),
        name=name,
        email=f"{name.lower().replace(' ', '.')}-{uuid.uuid4().hex[:8]}@example.test",
        password_hash="not-a-real-hash",
        role_id=role.role_id,
        is_active=True,
    )
    session.add(user)
    await session.flush()
    # .category/.categories eager-loaded too — OrganizationService's
    # _to_node (reached indirectly via get_subordinate_user_ids in
    # other tests reusing this same throwaway-user shape) reads
    # user.categories for every node; a lazy access there raises
    # MissingGreenlet under the async session if not preloaded.
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


async def _make_category(session, name: str) -> Category:
    category = Category(category_id=uuid.uuid4(), category_name=name)
    session.add(category)
    await session.flush()
    return category


@pytest.fixture
async def fixture(db_session):
    super_admin_role = await _get_role(db_session, "Super Admin")
    site_lead_role = await _get_role(db_session, "Site Lead")
    am_role = await _get_role(db_session, "Account Manager")
    team_lead_role = await _get_role(db_session, "Team Lead")
    staff_role = await _get_role(db_session, "Staff")
    client_role = await _get_role(db_session, "Client")

    super_admin = await _make_user(db_session, name="Test Super Admin RM", role=super_admin_role)
    site_lead = await _make_user(db_session, name="Test Site Lead RM", role=site_lead_role)
    am = await _make_user(db_session, name="Test AM Self RM", role=am_role)
    other_am = await _make_user(db_session, name="Test Other AM RM", role=am_role)
    team_lead = await _make_user(db_session, name="Test TL RM", role=team_lead_role)
    staff = await _make_user(db_session, name="Test Staff RM", role=staff_role)
    client = await _make_user(db_session, name="Test Client RM", role=client_role)

    # `has_permission` reads the plain `.permissions` attribute the
    # JWT/auth layer normally injects onto `current_user` post-login
    # (PermissionResolverService's computed effective set) — a
    # throwaway ORM row built directly in this transaction has no such
    # attribute, so it must be simulated explicitly here, same
    # convention as every other real-DB authorization test in this
    # suite (e.g. test_user_delete_authorization.py). Only Super
    # Admin/Site Lead simulate holding the broad admin permission —
    # every other actor explicitly holds nothing, so their outcome is
    # governed purely by the role/identity self-service rule under
    # test, never an accidental real seed grant.
    super_admin.permissions = ["org:manage_reporting_managers"]
    site_lead.permissions = ["org:manage_reporting_managers"]
    am.permissions = []
    other_am.permissions = []
    team_lead.permissions = []
    staff.permissions = []
    client.permissions = []

    category = await _make_category(db_session, f"Test Category RM {uuid.uuid4().hex[:8]}")
    other_category = await _make_category(db_session, f"Test Category RM Other {uuid.uuid4().hex[:8]}")

    return {
        "super_admin": super_admin,
        "site_lead": site_lead,
        "am": am,
        "other_am": other_am,
        "team_lead": team_lead,
        "staff": staff,
        "client": client,
        "category": category,
        "other_category": other_category,
    }


async def test_am_can_assign_and_revoke_their_own_mapping(db_session, fixture):
    service = _build_service(db_session)
    am = fixture["am"]
    category = fixture["category"]

    response = await service.assign(
        ReportingManagerAssign(account_manager_id=am.user_id, category_id=category.category_id),
        actor=am,
    )
    assert response.account_manager_id == am.user_id

    await service.revoke(response.id, actor=am)
    remaining = await service.list_by_account_manager(am.user_id)
    assert all(r.category_id != category.category_id for r in remaining)


async def test_am_cannot_assign_another_ams_mapping(db_session, fixture):
    service = _build_service(db_session)
    am = fixture["am"]
    other_am = fixture["other_am"]
    category = fixture["category"]

    with pytest.raises(HTTPException) as exc_info:
        await service.assign(
            ReportingManagerAssign(
                account_manager_id=other_am.user_id, category_id=category.category_id
            ),
            actor=am,
        )
    assert exc_info.value.status_code == 403


async def test_am_cannot_revoke_another_ams_mapping(db_session, fixture):
    service = _build_service(db_session)
    site_lead = fixture["site_lead"]
    am = fixture["am"]
    other_am = fixture["other_am"]
    category = fixture["category"]

    # Site Lead sets up other_am's mapping (admin path, unaffected by
    # this fix) — then `am` must not be able to revoke it.
    mapping = await service.assign(
        ReportingManagerAssign(
            account_manager_id=other_am.user_id, category_id=category.category_id
        ),
        actor=site_lead,
    )

    with pytest.raises(HTTPException) as exc_info:
        await service.revoke(mapping.id, actor=am)
    assert exc_info.value.status_code == 403


async def test_super_admin_and_site_lead_can_manage_any_am_mapping(db_session, fixture):
    service = _build_service(db_session)
    other_am = fixture["other_am"]
    category = fixture["category"]
    other_category = fixture["other_category"]

    super_admin_mapping = await service.assign(
        ReportingManagerAssign(
            account_manager_id=other_am.user_id, category_id=category.category_id
        ),
        actor=fixture["super_admin"],
    )
    await service.revoke(super_admin_mapping.id, actor=fixture["super_admin"])

    site_lead_mapping = await service.assign(
        ReportingManagerAssign(
            account_manager_id=other_am.user_id, category_id=other_category.category_id
        ),
        actor=fixture["site_lead"],
    )
    await service.revoke(site_lead_mapping.id, actor=fixture["site_lead"])


@pytest.mark.parametrize("actor_key", ["team_lead", "staff", "client"])
async def test_unauthorized_roles_are_denied(db_session, fixture, actor_key):
    service = _build_service(db_session)
    actor = fixture[actor_key]
    category = fixture["category"]

    with pytest.raises(HTTPException) as exc_info:
        await service.assign(
            ReportingManagerAssign(
                account_manager_id=fixture["am"].user_id, category_id=category.category_id
            ),
            actor=actor,
        )
    assert exc_info.value.status_code == 403


async def test_list_visible_scopes_non_privileged_am_to_their_own_mappings(db_session, fixture):
    service = _build_service(db_session)
    site_lead = fixture["site_lead"]
    am = fixture["am"]
    other_am = fixture["other_am"]
    category = fixture["category"]
    other_category = fixture["other_category"]

    await service.assign(
        ReportingManagerAssign(account_manager_id=am.user_id, category_id=category.category_id),
        actor=site_lead,
    )
    await service.assign(
        ReportingManagerAssign(
            account_manager_id=other_am.user_id, category_id=other_category.category_id
        ),
        actor=site_lead,
    )

    # Non-privileged AM with no filters sees only their own mapping.
    unfiltered = await service.list_visible(am)
    assert all(r.account_manager_id == am.user_id for r in unfiltered)
    assert any(r.category_id == category.category_id for r in unfiltered)

    # Asking about a DIFFERENT AM/category via query params must never
    # leak that other AM's mapping — since `am` has no mapping to
    # `other_category`, this correctly comes back empty rather than
    # falling back to `am`'s unrelated own mapping.
    other_scoped = await service.list_visible(
        am, account_manager_id=other_am.user_id, category_id=other_category.category_id
    )
    assert other_scoped == []

    # Filtering to a category `am` IS actually mapped to still works.
    own_scoped = await service.list_visible(am, category_id=category.category_id)
    assert any(r.account_manager_id == am.user_id for r in own_scoped)

    # Privileged actor sees the real, unrestricted, filtered view.
    admin_visible = await service.list_visible(site_lead, category_id=other_category.category_id)
    assert any(r.account_manager_id == other_am.user_id for r in admin_visible)


async def test_list_visible_denies_unauthorized_role(db_session, fixture):
    service = _build_service(db_session)
    with pytest.raises(HTTPException) as exc_info:
        await service.list_visible(fixture["staff"])
    assert exc_info.value.status_code == 403
