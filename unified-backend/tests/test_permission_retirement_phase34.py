# test_permission_retirement_phase34.py
#
# Phase 34 (RBAC Enforcement Audit): retires ticket:acknowledge_escalation
# — confirmed genuinely unenforced anywhere in the codebase (a fresh
# repo-wide grep found zero ensure_has_permission/has_permission calls
# referencing this string) via the same established
# DEPRECATED_PERMISSIONS mechanism already used in Phases 16, 21, 23,
# 33.
#
# Escalation acknowledgement is, and remains, strictly owner_ids-
# membership gated (EscalationService.acknowledge/confirm_assignment)
# — a deliberate design (see that method's own extensive comments):
# this permission was granted "Full" (unscoped) to Account
# Manager/Team Lead/Site Lead/Super Admin regardless of whether the
# escalation chain had actually reached their level, so it was never
# safe to use as a permission-based fallback (it would let a
# supervisor "jump the queue"). Retiring the catalog row changes
# nothing about how escalation acknowledgement actually works.
#
# NOTE: three other permissions considered for retirement this phase —
# ticket:system_config, ticket:view_audit_trail, ticket:view_dashboard_kpis
# — were investigated and explicitly NOT retired. Fresh verification
# found ticket:view_audit_trail and ticket:view_dashboard_kpis are
# genuinely, actively enforced in the backend (interaction_service.py:617,
# ticket_service.py:803) — retiring either catalog row while leaving
# that ensure_has_permission call in place would make the call fail for
# every user, breaking real functionality. ticket:system_config was
# found to be genuinely, deliberately reserved for a real, still-
# unbuilt future capability (seed.py's own comments). See the RBAC
# audit artifact, Phase 34, for the full reasoning on all three.
#
# Mirrors test_permission_retirement_phase33.py's own structure. Run
# individually if combined with other DB-touching test files, per this
# repo's documented pytest-asyncio event-loop-scope convention.

import sys
from pathlib import Path

import pytest
from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts" / "rbac_seed"))
import seed as seed_module  # noqa: E402

from app.database.session import AsyncSessionLocal, engine
from app.rbac.models import Permission, Role, RolePermission

RETIRED_PERMISSION = "ticket:acknowledge_escalation"

# Permissions explicitly investigated and kept this phase — asserting
# their presence guards against an off-by-one edit accidentally
# removing one of them while retiring the sibling above.
KEPT_CANDIDATES = [
    "ticket:system_config",
    "ticket:view_audit_trail",
    "ticket:view_dashboard_kpis",
]

UNCHANGED_SIBLINGS = [
    "ticket:view_escalated",
    "communication:reply_external",
    "communication:attach_to_ticket",
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


@pytest.mark.parametrize("kept", KEPT_CANDIDATES)
def test_investigated_but_kept_permission_still_active(kept):
    """The single most important regression guard in this file: three
    other candidates were investigated this phase and deliberately NOT
    retired (real backend enforcement, or a genuinely reserved future
    capability) — confirms none of them were accidentally caught up in
    this retirement."""
    names = {name for name, _ in seed_module.DEFAULT_PERMISSIONS}
    assert kept in names, f"{kept} was unexpectedly removed — it was investigated and explicitly KEPT this phase"


def test_no_unrelated_sibling_permission_was_touched():
    names = {name for name, _ in seed_module.DEFAULT_PERMISSIONS}
    for sibling in UNCHANGED_SIBLINGS:
        assert sibling in names, f"{sibling} was unexpectedly removed"

    am_grants = seed_module.DEFAULT_ROLES["Account Manager"]
    tl_grants = seed_module.DEFAULT_ROLES["Team Lead"]
    assert "ticket:view_escalated" in am_grants
    assert "ticket:view_escalated" in tl_grants


# ---------------------------------------------------------
# 2. DB-backed verification
# ---------------------------------------------------------


async def test_retired_permission_not_in_live_database(db_session):
    result = await db_session.execute(
        select(Permission).where(Permission.permission_name == RETIRED_PERMISSION)
    )
    assert result.scalar_one_or_none() is None


@pytest.mark.parametrize("kept", KEPT_CANDIDATES)
async def test_investigated_but_kept_permission_still_in_live_database(db_session, kept):
    result = await db_session.execute(
        select(Permission).where(Permission.permission_name == kept)
    )
    assert result.scalar_one_or_none() is not None, f"{kept} was unexpectedly removed from the live database"


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


async def test_account_manager_and_team_lead_still_hold_view_escalated(db_session):
    """Escalation-visibility itself (a distinct, separate permission,
    ticket:view_escalated) is completely unaffected by retiring the
    acknowledge permission — confirms both roles that lost the
    acknowledge grant kept the unrelated visibility grant."""
    for role_name in ("Account Manager", "Team Lead"):
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
        assert "ticket:view_escalated" in names, f"{role_name} unexpectedly lost ticket:view_escalated"
