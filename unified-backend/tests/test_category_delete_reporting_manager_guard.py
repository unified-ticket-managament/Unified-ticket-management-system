# test_category_delete_reporting_manager_guard.py
#
# Coverage for two fixes to CategoryService, both from the same pass:
#
#   1. delete_category used to only check assigned_user_count
#      (user_categories rows) before deleting — it never looked at
#      reporting_manager_teams, whose category_id FK is ON DELETE
#      CASCADE, so deleting a category used to silently wipe out any
#      Account Manager's active Reporting Manager mapping to it with
#      no warning. Fixed with a pre-delete guard.
#   2. Category create/update/delete/set-members now write an
#      audit_logs row via the existing AuditLogService (previously
#      wrote none at all).
#
# Runs against the real (dev) database inside a transaction that is
# always rolled back at the end. Run this file individually per this
# repo's own documented pytest-asyncio DB-touching-file caveat.

import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import joinedload, selectinload
from shared_models.models import Role, User

from app.database.session import AsyncSessionLocal, engine
from app.rbac.repositories.audit_log_repository import AuditLogRepository
from app.rbac.repositories.category_repository import CategoryRepository
from app.rbac.repositories.reporting_manager_repository import ReportingManagerRepository
from app.rbac.repositories.role_repository import RoleRepository
from app.rbac.repositories.user_repository import UserRepository
from app.rbac.schemas.category import CategoryCreate, CategoryMembersUpdate, CategoryUpdate
from app.rbac.schemas.reporting_manager import ReportingManagerAssign
from app.rbac.services.audit_log_service import AuditLogService
from app.rbac.services.category_service import CategoryService
from app.rbac.services.reporting_manager_service import ReportingManagerService


@pytest.fixture
async def db_session():
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.rollback()
    await engine.dispose()


def _build_category_service(session) -> CategoryService:
    return CategoryService(
        category_repository=CategoryRepository(session),
        user_repository=UserRepository(session),
        reporting_manager_repository=ReportingManagerRepository(session),
        audit_log_service=AuditLogService(audit_log_repository=AuditLogRepository(session)),
    )


def _build_reporting_manager_service(session) -> ReportingManagerService:
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


async def test_category_with_active_reporting_manager_mapping_cannot_be_deleted(db_session):
    am_role = await _get_role(db_session, "Account Manager")
    am = await _make_user(db_session, name="Test AM Delete Guard", role=am_role)

    category_service = _build_category_service(db_session)
    reporting_manager_service = _build_reporting_manager_service(db_session)

    category = await category_service.create_category(
        CategoryCreate(category_name=f"Test Category Delete Guard {uuid.uuid4().hex[:8]}"),
        actor=am,
    )
    await reporting_manager_service.assign(
        ReportingManagerAssign(account_manager_id=am.user_id, category_id=category.category_id),
        actor=am,
    )

    with pytest.raises(HTTPException) as exc_info:
        await category_service.delete_category(category.category_id, actor=am)
    assert exc_info.value.status_code == 400
    assert "Reporting Manager" in exc_info.value.detail


async def test_category_without_reporting_manager_mapping_deletes_as_before(db_session):
    am_role = await _get_role(db_session, "Account Manager")
    am = await _make_user(db_session, name="Test AM No Mapping", role=am_role)

    category_service = _build_category_service(db_session)

    category = await category_service.create_category(
        CategoryCreate(category_name=f"Test Category No Mapping {uuid.uuid4().hex[:8]}"),
        actor=am,
    )

    # Must not raise — pre-existing member-count guard behavior is
    # unaffected by the new Reporting Manager check.
    await category_service.delete_category(category.category_id, actor=am)

    with pytest.raises(HTTPException) as exc_info:
        await category_service.get_category(category.category_id)
    assert exc_info.value.status_code == 404


async def test_category_mutations_write_audit_log_rows(db_session):
    am_role = await _get_role(db_session, "Account Manager")
    staff_role = await _get_role(db_session, "Staff")
    am = await _make_user(db_session, name="Test AM Audit", role=am_role)
    staff = await _make_user(db_session, name="Test Staff Audit", role=staff_role)

    category_service = _build_category_service(db_session)
    audit_log_repository = AuditLogRepository(db_session)

    category = await category_service.create_category(
        CategoryCreate(category_name=f"Test Category Audit {uuid.uuid4().hex[:8]}"),
        actor=am,
    )
    await category_service.update_category(
        category.category_id, CategoryUpdate(category_name=f"{category.category_name}-renamed"), actor=am
    )
    await category_service.set_members(category.category_id, [staff.user_id], actor=am)
    # Clear membership again before deleting — delete_category's
    # pre-existing assigned_user_count guard would otherwise 400 here,
    # which is correct behavior but not what this test is checking.
    await category_service.set_members(category.category_id, [], actor=am)
    await category_service.delete_category(category.category_id, actor=am)

    logs, _total = await audit_log_repository.get_all(page=1, page_size=200)
    actions_for_category = {
        log.action for log in logs if log.entity_id == str(category.category_id)
    }
    assert actions_for_category == {
        "category.create",
        "category.update",
        "category.members_set",
        "category.delete",
    }
