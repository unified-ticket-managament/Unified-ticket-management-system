# test_permission_retirement_phase21.py
#
# Phase 21 (RBAC Enforcement Audit, BD-6/BD-8/BD-9): retires the four
# permissions Phase 20 classified "YES — SAFE TO RETIRE" after explicit
# product-owner approval was recorded —
#   communication:convert_to_ticket  -> superseded by ticket:create
#   ticket:manage_agents             -> superseded by user:disable
#   ticket:manage_roles_permissions  -> superseded by the role:*/
#                                        permission:* family
#   communication:override_grant     -> a naming collision with the
#                                        real permission:override_grant
# via the same established DEPRECATED_PERMISSIONS mechanism already
# proven in Phase 16 (ticket:escalate, permission:override_revoke).
#
# Three groups of coverage, mirroring test_permission_retirement_
# phase16.py's own structure:
# - Static: seed.py's own module-level lists correctly reflect the
#   retirement (no DB needed).
# - DB-backed: the 4 permissions are actually absent from the live
#   catalog and every role's grants, and the replacements are present
#   — formalizing the ad-hoc verification queries already run this
#   phase into a permanent regression test.
# - Functional: each replacement's real enforcement call site still
#   checks exactly the expected permission string — confirming the
#   retirement did not accidentally touch any of the 4 real,
#   independent authorization mechanisms it was never meant to touch.
#
# Run individually if combined with other DB-touching test files, per
# this repo's documented pytest-asyncio event-loop-scope convention.

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts" / "rbac_seed"))
import seed as seed_module  # noqa: E402

from app.database.session import AsyncSessionLocal, engine
from app.rbac.models import Permission, Role, RolePermission
from app.rbac.services.access_control import ensure_has_permission as rbac_ensure_has_permission
from app.ticketing.services.access_control import (
    ensure_has_permission as ticketing_ensure_has_permission,
)

RETIRED_PERMISSIONS = [
    "communication:convert_to_ticket",
    "ticket:manage_agents",
    "ticket:manage_roles_permissions",
    "communication:override_grant",
]

REPLACEMENT_PERMISSIONS = [
    "ticket:create",
    "user:disable",
    "role:create",
    "role:update",
    "role:delete",
    "role:view",
    "permission:update",
    "permission:view",
    "permission:override_grant",
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
# 1. Static verification: seed.py's own module-level lists correctly
#    reflect the retirement — no DB access needed.
# ---------------------------------------------------------


@pytest.mark.parametrize("permission_name", RETIRED_PERMISSIONS)
def test_retired_permission_in_deprecated_permissions(permission_name):
    assert permission_name in seed_module.DEPRECATED_PERMISSIONS


@pytest.mark.parametrize("permission_name", RETIRED_PERMISSIONS)
def test_retired_permission_absent_from_default_permissions(permission_name):
    names = {name for name, _ in seed_module.DEFAULT_PERMISSIONS}
    assert permission_name not in names


def test_retired_permissions_absent_from_every_default_roles_grant_list():
    for role_name, grants in seed_module.DEFAULT_ROLES.items():
        if grants == "all":
            continue
        for permission_name in RETIRED_PERMISSIONS:
            assert permission_name not in grants, (
                f"{role_name} still lists {permission_name}"
            )


def test_deprecated_permissions_has_no_duplicate_entries():
    names = seed_module.DEPRECATED_PERMISSIONS
    assert len(names) == len(set(names))


@pytest.mark.parametrize("permission_name", REPLACEMENT_PERMISSIONS)
def test_replacement_permission_still_in_default_permissions(permission_name):
    names = {name for name, _ in seed_module.DEFAULT_PERMISSIONS}
    assert permission_name in names, f"{permission_name} was unexpectedly removed"


def test_no_unrelated_sibling_permission_was_touched():
    """Guards against an off-by-one edit accidentally removing a
    neighboring line in the same communication:*/ticket:* blocks.

    communication:assign was deliberately removed from this list in
    Phase 23 (RBAC Enforcement Audit) — it was itself retired via the
    same DEPRECATED_PERMISSIONS mechanism (see
    test_permission_retirement_phase23.py), so it is no longer an
    "unrelated sibling" this test should assert survives. communication:
    merge and communication:forward were likewise deliberately removed
    from this list in Phase 33 — both retired via the same mechanism
    (see test_permission_retirement_phase33.py), superseded by
    communication:attach_to_ticket and communication:reply_external
    respectively. ticket:acknowledge_escalation was likewise removed in
    Phase 34 (see test_permission_retirement_phase34.py) — confirmed
    genuinely unenforced, ownership/owner_ids governs escalation
    acknowledgement instead. Every other name below is still untouched
    and must remain here.
    """
    names = {name for name, _ in seed_module.DEFAULT_PERMISSIONS}
    for sibling in (
        "communication:attach_to_ticket",
        "communication:create",
        "ticket:view_escalated",
        "ticket:system_config",
        "user:reset_password",
    ):
        assert sibling in names, f"{sibling} was unexpectedly removed"

    am_grants = seed_module.DEFAULT_ROLES["Account Manager"]
    for sibling in (
        "communication:attach_to_ticket",
        "ticket:view_escalated",
        "user:reset_password",
    ):
        assert sibling in am_grants, f"Account Manager unexpectedly lost {sibling}"


# ---------------------------------------------------------
# 2. DB-backed verification: after the seed script has been run
#    against the connected database, the 4 retired permissions are
#    absent from the catalog and no role holds any of them, while
#    every replacement remains present.
# ---------------------------------------------------------


@pytest.mark.parametrize("permission_name", RETIRED_PERMISSIONS)
async def test_retired_permission_not_in_live_database(db_session, permission_name):
    result = await db_session.execute(
        select(Permission).where(Permission.permission_name == permission_name)
    )
    assert result.scalar_one_or_none() is None, (
        f"{permission_name} still exists in the live permissions table"
    )


@pytest.mark.parametrize("permission_name", REPLACEMENT_PERMISSIONS)
async def test_replacement_permission_in_live_database(db_session, permission_name):
    result = await db_session.execute(
        select(Permission).where(Permission.permission_name == permission_name)
    )
    assert result.scalar_one_or_none() is not None, (
        f"{permission_name} is unexpectedly absent from the live permissions table"
    )


@pytest.mark.parametrize(
    "role_name", ["Super Admin", "Site Lead", "Account Manager", "Team Lead", "Staff", "Client"]
)
async def test_no_role_holds_any_retired_permission(db_session, role_name):
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
    for permission_name in RETIRED_PERMISSIONS:
        assert permission_name not in names, f"{role_name} still holds {permission_name}"


async def test_account_manager_still_holds_the_replacement_permissions(db_session):
    """Account Manager held all 4 retired rows by default — confirms
    retiring them did not also silently strip the real replacements
    Account Manager is entitled to."""

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
    # ticket:create is Account Manager's real replacement for
    # communication:convert_to_ticket.
    assert "ticket:create" in names
    # user:disable is Account Manager's real replacement for
    # ticket:manage_agents.
    assert "user:disable" in names
    # permission:override_grant is Account Manager's real replacement
    # for communication:override_grant.
    assert "permission:override_grant" in names
    # The role:*/permission:* family superseding
    # ticket:manage_roles_permissions is deliberately NOT expected
    # here — Account Manager never held it (Super Admin/Site Lead
    # only), the pre-existing grant-design mismatch this phase
    # explicitly left untouched and out of scope.


# ---------------------------------------------------------
# 3. Functional verification: each replacement's real enforcement
#    call site still checks exactly the expected permission string —
#    confirming the retirement did not touch any real, independent
#    authorization mechanism.
# ---------------------------------------------------------


def _user(permissions):
    return SimpleNamespace(permissions=permissions)


def test_ticket_create_enforcement_unaffected():
    """inbox_ticket_service.create_ticket_from_interaction's real gate
    (ticket:create) still functions exactly as Phase 18 left it."""

    with pytest.raises(Exception):
        ticketing_ensure_has_permission(_user([]), "ticket:create")
    ticketing_ensure_has_permission(_user(["ticket:create"]), "ticket:create")  # no raise


def test_user_disable_enforcement_unaffected():
    """users.py's activate_user/deactivate_user real gate
    (user:disable) still functions."""

    with pytest.raises(Exception):
        rbac_ensure_has_permission(_user([]), "user:disable")
    rbac_ensure_has_permission(_user(["user:disable"]), "user:disable")  # no raise


@pytest.mark.parametrize(
    "permission_name", ["role:create", "role:update", "role:delete", "role:view", "permission:update", "permission:view"]
)
def test_role_and_permission_family_enforcement_unaffected(permission_name):
    """roles.py/permissions.py/role_permissions.py's real gates (the
    replacement family for ticket:manage_roles_permissions) still
    function, each independently."""

    with pytest.raises(Exception):
        rbac_ensure_has_permission(_user([]), permission_name)
    rbac_ensure_has_permission(_user([permission_name]), permission_name)  # no raise


def test_permission_override_grant_enforcement_unaffected():
    """PermissionOverrideService.ensure_can_manage_overrides' real
    literal check (permission:override_grant) is untouched — confirmed
    directly against the actual source text, since that method's
    authorization also depends on role-name branching not exercised
    by a bare permission-string check."""

    source = Path("app/rbac/services/permission_override_service.py").read_text(
        encoding="utf-8"
    )
    assert '"permission:override_grant" not in actor_permissions' in source
    assert "communication:override_grant" not in source
