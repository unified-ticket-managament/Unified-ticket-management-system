# test_permission_retirement_phase16.py
#
# Phase 16 (RBAC Enforcement Audit, BD-4/BD-7): retires the unused
# ticket:escalate and permission:override_revoke permission catalog
# rows via the established seed.py DEPRECATED_PERMISSIONS mechanism —
# the exact same pattern already used for ticket:bulk_reassign,
# ticket:configure_routing, ticket:edit_ticket, ticket:close, and
# ticket:manage_attachments.
#
# Both permissions were confirmed, across 5+ independent phases (7, 9,
# 10, 11, 16), to have zero real enforcement anywhere:
# - ticket:escalate: EscalationService.manual_escalate authorizes via
#   ticket visibility (fresh escalation) and strict owner_ids
#   membership (advancing an active one) — never this permission.
# - permission:override_revoke: revoking is already fully covered by
#   two real, independently-designed mechanisms — the shared
#   permission:override_grant gate (direct override revoke) and
#   PermissionRequestService.revoke()'s ownership check (approved-
#   request revoke).
#
# This file verifies (1) the retirement is correctly reflected in
# seed.py's own module-level lists, (2) both permissions are actually
# absent from the connected database's catalog and every role's
# grants after the seed script has been run, and (3) the two real
# mechanisms this retirement must NOT touch are still exactly as they
# were — neither service file was modified by this phase.
#
# Items (1) and (3) are pure/lightweight and need no DB. Item (2) is
# DB-backed (read-only queries against the already-seeded state) —
# run this file individually per this repo's documented DB-touching
# test-file convention.

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts" / "rbac_seed"))
import seed as seed_module  # noqa: E402

from app.database.session import AsyncSessionLocal, engine
from app.rbac.models import Permission, Role, RolePermission
from app.rbac.services.permission_override_service import (
    PermissionOverrideService,
)
from app.rbac.services.permission_request_service import (
    PermissionRequestService,
)


@pytest.fixture
async def db_session():
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.rollback()
    await engine.dispose()


# ---------------------------------------------------------
# 1. Static verification: seed.py's own module-level lists correctly
#    reflect the retirement — no DB access needed.
# ---------------------------------------------------------


def test_both_permissions_are_in_deprecated_permissions():
    assert "ticket:escalate" in seed_module.DEPRECATED_PERMISSIONS
    assert "permission:override_revoke" in seed_module.DEPRECATED_PERMISSIONS


def test_neither_permission_remains_in_default_permissions():
    names = {name for name, _ in seed_module.DEFAULT_PERMISSIONS}
    assert "ticket:escalate" not in names
    assert "permission:override_revoke" not in names


def test_neither_permission_remains_in_any_default_roles_grant_list():
    for role_name, grants in seed_module.DEFAULT_ROLES.items():
        if grants == "all":
            continue  # Super Admin computes from DEFAULT_PERMISSIONS, already checked above
        assert "ticket:escalate" not in grants, f"{role_name} still lists ticket:escalate"
        assert "permission:override_revoke" not in grants, (
            f"{role_name} still lists permission:override_revoke"
        )


def test_deprecated_permissions_has_no_duplicate_entries():
    """Sanity check on the edit itself — adding an entry twice would
    make the cleanup loop run twice for no reason (harmless, since
    it's a no-op the second time, but worth catching)."""
    names = seed_module.DEPRECATED_PERMISSIONS
    assert len(names) == len(set(names))


def test_no_unrelated_permission_was_touched():
    """Confirms the sibling permissions this retirement sits next to
    in both DEFAULT_PERMISSIONS and DEFAULT_ROLES are untouched —
    guards against an off-by-one edit accidentally removing a
    neighboring line.

    ticket:acknowledge_escalation was deliberately removed from this
    list in Phase 34 (RBAC Enforcement Audit) — it was itself retired
    via the same DEPRECATED_PERMISSIONS mechanism this file's own
    retirements use (see test_permission_retirement_phase34.py),
    confirmed genuinely unenforced (ownership/owner_ids governs
    escalation acknowledgement, not this permission). It is no longer
    an "unrelated sibling" this test should assert survives.
    """
    names = {name for name, _ in seed_module.DEFAULT_PERMISSIONS}
    assert "permission:override_grant" in names
    assert "permission:view" in names
    assert "ticket:close_ticket" in names
    assert "ticket:reopen" in names
    assert "ticket:upload_attachment" in names

    am_grants = seed_module.DEFAULT_ROLES["Account Manager"]
    assert "permission:override_grant" in am_grants
    assert "ticket:close_ticket" in am_grants
    assert "ticket:reopen" in am_grants

    tl_grants = seed_module.DEFAULT_ROLES["Team Lead"]
    assert "ticket:upload_attachment" in tl_grants
    assert "ticket:view_escalated" in tl_grants


# ---------------------------------------------------------
# 2. DB-backed verification: after the seed script has been run
#    against the connected database, neither permission exists in the
#    catalog and no role holds either.
# ---------------------------------------------------------


async def test_neither_permission_exists_in_the_database(db_session):
    for name in ("ticket:escalate", "permission:override_revoke"):
        result = await db_session.execute(
            select(Permission).where(Permission.permission_name == name)
        )
        assert result.scalar_one_or_none() is None, f"{name} still exists in permissions table"


@pytest.mark.parametrize(
    "role_name", ["Super Admin", "Site Lead", "Account Manager", "Team Lead", "Staff", "Client"]
)
async def test_no_role_holds_either_retired_permission(db_session, role_name):
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
    assert "ticket:escalate" not in names
    assert "permission:override_revoke" not in names


# ---------------------------------------------------------
# 3. The two real mechanisms this retirement must not touch —
#    confirmed unchanged. Neither service file was modified this
#    phase; these tests exist as a permanent guard against a future
#    change accidentally coupling either mechanism to the now-retired
#    permission:override_revoke string.
# ---------------------------------------------------------


async def test_direct_override_management_still_gated_by_override_grant_only():
    """PermissionOverrideService.ensure_can_manage_overrides must
    still check permission:override_grant alone — never
    permission:override_revoke, which no longer exists as a row and
    was never checked by this method to begin with."""

    service = PermissionOverrideService(
        user_repository=None,
        permission_repository=None,
        permission_override_repository=None,
        organization_service=None,
        permission_resolver=SimpleNamespace(
            get_effective_permissions=lambda user: _resolve([])
        ),
        audit_log_service=None,
    )

    actor = SimpleNamespace(
        role=SimpleNamespace(name="Team Lead"),
        user_id="actor-id",
        permissions=[],
    )
    target = SimpleNamespace(user_id="target-id")

    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc_info:
        await service.ensure_can_manage_overrides(actor, target)
    assert exc_info.value.status_code == 403


async def _resolve(permissions):
    return (permissions, {}, None)


def test_permission_request_revoke_still_ownership_gated_not_by_a_permission():
    """PermissionRequestService._can_revoke must remain a pure
    ownership check (original approver or Super Admin) — it never
    read permission:override_revoke before this phase and does not
    now."""

    from app.rbac.models.permission_request import PermissionRequestStatus

    service = PermissionRequestService.__new__(PermissionRequestService)

    approver_id = "approver-1"
    other_id = "someone-else"

    approved_request = SimpleNamespace(
        status=PermissionRequestStatus.APPROVED,
        reviewed_by=approver_id,
    )

    original_approver = SimpleNamespace(
        role=SimpleNamespace(name="Team Lead"), user_id=approver_id
    )
    super_admin = SimpleNamespace(role=SimpleNamespace(name="Super Admin"), user_id=other_id)
    unrelated_agent = SimpleNamespace(
        role=SimpleNamespace(name="Team Lead"), user_id=other_id
    )

    assert service._can_revoke(original_approver, approved_request) is True
    assert service._can_revoke(super_admin, approved_request) is True
    assert service._can_revoke(unrelated_agent, approved_request) is False

    pending_request = SimpleNamespace(
        status=PermissionRequestStatus.PENDING, reviewed_by=approver_id
    )
    assert service._can_revoke(original_approver, pending_request) is False
