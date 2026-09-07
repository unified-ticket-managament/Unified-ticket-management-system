# test_permission_retirement_phase33.py
#
# Phase 33 (RBAC Enforcement Audit): retires two duplicate/superseded
# permissions —
#
#   communication:forward     -> superseded by communication:reply_external
#   communication:merge       -> superseded by communication:attach_to_ticket
#
# — confirmed genuinely unenforced anywhere in the codebase across
# three independent investigations (Phase 9's original capability
# trace, Phase 31's re-verification, Phase 32's adversarial re-trace
# with an expanded keyword sweep) via the same established
# DEPRECATED_PERMISSIONS mechanism already used in Phases 16, 21, 23.
#
# Mirrors test_permission_retirement_phase21.py / phase23.py's own
# structure. Run individually if combined with other DB-touching test
# files, per this repo's documented pytest-asyncio event-loop-scope
# convention.

import sys
from pathlib import Path

import pytest
from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts" / "rbac_seed"))
import seed as seed_module  # noqa: E402

from app.database.session import AsyncSessionLocal, engine
from app.rbac.models import Permission, Role, RolePermission

RETIRED_PERMISSIONS = ["communication:forward", "communication:merge"]

# The two permissions each retired permission was found to be a
# duplicate of — must remain fully intact (still in the catalog, still
# granted to the same roles as before) since retiring the duplicate
# must never touch its replacement.
REPLACEMENT_PERMISSIONS = ["communication:reply_external", "communication:attach_to_ticket"]

# ticket:acknowledge_escalation was deliberately removed from this
# list in Phase 34 (RBAC Enforcement Audit) — it was itself retired
# via the same DEPRECATED_PERMISSIONS mechanism this file's own
# RETIRED_PERMISSIONS already exercises (see
# test_permission_retirement_phase34.py). It is no longer an
# "unrelated sibling" this test should assert survives.
UNCHANGED_SIBLINGS = [
    "communication:reply_external",
    "communication:attach_to_ticket",
    "communication:create",
    "communication:view_timeline",
    "communication:view_all",
    "communication:view_assigned",
    "communication:reply_internal",
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


@pytest.mark.parametrize("retired", RETIRED_PERMISSIONS)
def test_retired_permission_in_deprecated_permissions(retired):
    assert retired in seed_module.DEPRECATED_PERMISSIONS


@pytest.mark.parametrize("retired", RETIRED_PERMISSIONS)
def test_retired_permission_absent_from_default_permissions(retired):
    names = {name for name, _ in seed_module.DEFAULT_PERMISSIONS}
    assert retired not in names


@pytest.mark.parametrize("retired", RETIRED_PERMISSIONS)
def test_retired_permission_absent_from_every_default_roles_grant_list(retired):
    for role_name, grants in seed_module.DEFAULT_ROLES.items():
        if grants == "all":
            continue
        assert retired not in grants, f"{role_name} still lists {retired}"


def test_deprecated_permissions_has_no_duplicate_entries():
    names = seed_module.DEPRECATED_PERMISSIONS
    assert len(names) == len(set(names))


@pytest.mark.parametrize("replacement", REPLACEMENT_PERMISSIONS)
def test_replacement_permission_still_active(replacement):
    """The whole point of a duplicate retirement is that the real,
    enforced permission is left completely untouched — this is the
    single most important regression guard in this file."""
    names = {name for name, _ in seed_module.DEFAULT_PERMISSIONS}
    assert replacement in names, f"{replacement} (the replacement) was unexpectedly removed"

    am_grants = seed_module.DEFAULT_ROLES["Account Manager"]
    assert replacement in am_grants, f"Account Manager unexpectedly lost {replacement}"


def test_no_unrelated_sibling_permission_was_touched():
    """Guards against an off-by-one edit accidentally removing a
    neighboring line in the same communication:* block."""
    names = {name for name, _ in seed_module.DEFAULT_PERMISSIONS}
    for sibling in UNCHANGED_SIBLINGS:
        assert sibling in names, f"{sibling} was unexpectedly removed"


# ---------------------------------------------------------
# 2. DB-backed verification
# ---------------------------------------------------------


@pytest.mark.parametrize("retired", RETIRED_PERMISSIONS)
async def test_retired_permission_not_in_live_database(db_session, retired):
    result = await db_session.execute(
        select(Permission).where(Permission.permission_name == retired)
    )
    assert result.scalar_one_or_none() is None


@pytest.mark.parametrize("replacement", REPLACEMENT_PERMISSIONS)
async def test_replacement_permission_still_in_live_database(db_session, replacement):
    result = await db_session.execute(
        select(Permission).where(Permission.permission_name == replacement)
    )
    assert result.scalar_one_or_none() is not None


@pytest.mark.parametrize("retired", RETIRED_PERMISSIONS)
@pytest.mark.parametrize(
    "role_name", ["Super Admin", "Site Lead", "Account Manager", "Team Lead", "Staff", "Client"]
)
async def test_no_role_holds_either_retired_permission(db_session, role_name, retired):
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
    assert retired not in names


async def test_account_manager_still_holds_both_replacement_permissions(db_session):
    """Staff's own effective-access-unchanged claim rests on
    reply_external, not on the retired communication:forward row —
    this test instead confirms the role that legitimately used both
    retired rows (Account Manager) still has full access to both real
    replacement capabilities post-retirement."""
    role = (
        await db_session.execute(select(Role).where(Role.name == "Account Manager"))
    ).scalar_one_or_none()
    if role is None:
        pytest.skip("No 'Account Manager' role seeded.")

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
    for replacement in REPLACEMENT_PERMISSIONS:
        assert replacement in names, f"Account Manager unexpectedly lost {replacement}"


async def test_staff_still_holds_reply_external(db_session):
    """The specific, previously-flagged grant asymmetry: Staff held
    communication:reply_external but never communication:forward.
    Confirms Staff's real Forward capability (via reply_external) is
    completely unaffected by retiring the unused forward row."""
    role = (
        await db_session.execute(select(Role).where(Role.name == "Staff"))
    ).scalar_one_or_none()
    if role is None:
        pytest.skip("No 'Staff' role seeded.")

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
    assert "communication:reply_external" in names
