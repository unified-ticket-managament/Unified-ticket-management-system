# test_permission_retirement_phase23.py
#
# Phase 23 (RBAC Enforcement Audit): retires communication:assign —
# confirmed genuinely dead across five independent investigations
# (Phases 19, 20, 22, 23, plus a final targeted re-trace immediately
# before this retirement) — via the same established
# DEPRECATED_PERMISSIONS mechanism already used in Phases 16 and 21.
#
# Mirrors test_permission_retirement_phase21.py's own structure.
# Run individually if combined with other DB-touching test files, per
# this repo's documented pytest-asyncio event-loop-scope convention.

import sys
from pathlib import Path

import pytest
from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts" / "rbac_seed"))
import seed as seed_module  # noqa: E402

from app.database.session import AsyncSessionLocal, engine
from app.rbac.models import Permission, Role, RolePermission

RETIRED_PERMISSION = "communication:assign"

# communication:merge and communication:forward were deliberately
# removed from this list in Phase 33 (RBAC Enforcement Audit) — both
# retired via the same DEPRECATED_PERMISSIONS mechanism this file's
# own RETIRED_PERMISSION already exercises (see
# test_permission_retirement_phase33.py), superseded by
# communication:attach_to_ticket and communication:reply_external
# respectively. They are no longer "unrelated siblings" this test
# should assert survive. ticket:acknowledge_escalation was likewise
# removed in Phase 34 (see test_permission_retirement_phase34.py) —
# confirmed genuinely unenforced, ownership/owner_ids governs
# escalation acknowledgement instead.
UNCHANGED_SIBLINGS = [
    "communication:attach_to_ticket",
    "communication:create",
    "communication:view_timeline",
    "communication:reply_external",
    "ticket:system_config",
    "user:reset_password",
]


@pytest.fixture
async def db_session():
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.rollback()
    await engine.dispose()


# ---------------------------------------------------------
# 1. Static verification
# ---------------------------------------------------------


def test_retired_permission_in_deprecated_permissions():
    assert RETIRED_PERMISSION in seed_module.DEPRECATED_PERMISSIONS


def test_retired_permission_absent_from_default_permissions():
    names = {name for name, _ in seed_module.DEFAULT_PERMISSIONS}
    assert RETIRED_PERMISSION not in names


def test_retired_permission_absent_from_every_default_roles_grant_list():
    for role_name, grants in seed_module.DEFAULT_ROLES.items():
        if grants == "all":
            continue
        assert RETIRED_PERMISSION not in grants, f"{role_name} still lists {RETIRED_PERMISSION}"


def test_deprecated_permissions_has_no_duplicate_entries():
    names = seed_module.DEPRECATED_PERMISSIONS
    assert len(names) == len(set(names))


def test_no_unrelated_sibling_permission_was_touched():
    names = {name for name, _ in seed_module.DEFAULT_PERMISSIONS}
    for sibling in UNCHANGED_SIBLINGS:
        assert sibling in names, f"{sibling} was unexpectedly removed"

    am_grants = seed_module.DEFAULT_ROLES["Account Manager"]
    for sibling in ("communication:attach_to_ticket", "communication:view_timeline"):
        assert sibling in am_grants, f"Account Manager unexpectedly lost {sibling}"


# ---------------------------------------------------------
# 2. DB-backed verification
# ---------------------------------------------------------


async def test_retired_permission_not_in_live_database(db_session):
    result = await db_session.execute(
        select(Permission).where(Permission.permission_name == RETIRED_PERMISSION)
    )
    assert result.scalar_one_or_none() is None


@pytest.mark.parametrize(
    "role_name", ["Super Admin", "Site Lead", "Account Manager", "Team Lead", "Staff", "Client"]
)
async def test_no_role_holds_the_retired_permission(db_session, role_name):
    role = (
        await db_session.execute(select(Role).where(Role.name == role_name))
    ).scalar_one_or_none()
    if role is None:
        pytest.skip(f"No {role_name!r} role seeded.")

    names = set(
        (
            await db_session.execute(
                select(Permission.permission_name)
                .join(RolePermission, RolePermission.permission_id == Permission.permission_id)
                .where(RolePermission.role_id == role.role_id)
            )
        )
        .scalars()
        .all()
    )
    assert RETIRED_PERMISSION not in names
