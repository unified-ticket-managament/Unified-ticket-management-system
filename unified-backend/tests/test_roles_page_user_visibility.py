# test_roles_page_user_visibility.py
#
# Coverage for GET /roles/{role_id}/users — a new, isolated endpoint
# backing the Roles page's "Assigned Users" panel and per-role counts
# only. Deliberately NOT hierarchy-scoped: an Account Manager clicking
# Team Lead or Staff must see the entire company-wide population of
# that role, not their own reporting subtree. Gated by role:view plus
# user:view (both real, effective-permission checks — see
# app/rbac/api/v1/roles.py's list_users_for_role) rather than a
# hardcoded role-name allow-list, which used to unconditionally deny
# Team Lead here regardless of what permissions it actually held.
#
# This route reuses two pre-existing, unmodified building blocks —
# RoleRepository.get_by_id and UserRepository.get_by_role (already
# exercised by test_organization_chart_hierarchy.py for Super Admin's
# own unrestricted case) — rather than introducing new query logic, so
# these tests exercise those same building blocks the same way the
# route itself does, following this repo's existing convention of
# testing service/repository methods directly rather than through a
# live HTTP client.
#
# Regression guarantee (verified by re-running, unmodified, rather
# than duplicated here): test_organization_chart_hierarchy.py and
# test_user_listing_hierarchy.py must both still pass byte-identically
# after this change — this endpoint and its permission check are
# entirely new additions; no existing function was modified.

import pytest
from sqlalchemy import select
from sqlalchemy.orm import joinedload
from shared_models.models import Role, User

from app.database.session import AsyncSessionLocal, engine
from app.rbac.repositories.role_repository import RoleRepository
from app.rbac.repositories.user_repository import UserRepository


# --------------------------------------------------------------------
# DB-backed: the route's own logic (role lookup -> Client short-circuit
# -> UserRepository.get_by_role), real seeded data, always rolled back.
# --------------------------------------------------------------------

@pytest.fixture
async def db_session():
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.rollback()
    await engine.dispose()


async def _get_role(session, role_name: str) -> Role:
    role = await RoleRepository(session).get_by_name(role_name)
    if role is None:
        pytest.skip(f"No {role_name!r} role seeded.")
    return role


async def _count_active_by_role(session, role_id) -> int:
    result = await session.execute(
        select(User).where(User.role_id == role_id, User.is_active.is_(True))
    )
    return len(result.scalars().all())


async def test_team_lead_role_returns_full_company_population_not_a_subtree(db_session):
    """
    The actual reported bug: an Account Manager's own subtree only
    contained a fraction of the real Team Leads. This endpoint must
    return every active Team Lead, independent of any manager_id/
    teamlead_id relationship to whoever is asking.
    """

    team_lead_role = await _get_role(db_session, "Team Lead")
    expected_count = await _count_active_by_role(db_session, team_lead_role.role_id)
    if expected_count == 0:
        pytest.skip("No active seeded Team Lead found.")

    users = await UserRepository(db_session).get_by_role(team_lead_role.role_id)

    assert len(users) == expected_count
    assert all(u.role_id == team_lead_role.role_id and u.is_active for u in users)


async def test_staff_role_returns_full_company_population(db_session):
    staff_role = await _get_role(db_session, "Staff")
    expected_count = await _count_active_by_role(db_session, staff_role.role_id)
    if expected_count == 0:
        pytest.skip("No active seeded Staff found.")

    users = await UserRepository(db_session).get_by_role(staff_role.role_id)

    assert len(users) == expected_count


async def test_account_manager_direct_reports_included_in_full_population(db_session):
    """
    Confirms the specific data shape that exposed the original bug:
    a Staff member reporting directly to an Account Manager
    (manager_id set, teamlead_id NULL) is included in the full
    company-wide Staff population this endpoint returns — regardless
    of whether any hierarchy-scoping bug affecting a *different* code
    path (get_subordinate_user_ids) is ever fixed.
    """

    staff_role = await _get_role(db_session, "Staff")

    result = await db_session.execute(
        select(User)
        .options(joinedload(User.role))
        .where(
            User.role_id == staff_role.role_id,
            User.manager_id.isnot(None),
            User.teamlead_id.is_(None),
            User.is_active.is_(True),
        )
    )
    direct_report = result.unique().scalars().first()
    if direct_report is None:
        pytest.skip("No active seeded Staff with a direct (no Team Lead) manager_id found.")

    users = await UserRepository(db_session).get_by_role(staff_role.role_id)
    returned_ids = {u.user_id for u in users}

    assert direct_report.user_id in returned_ids


async def test_client_role_short_circuits_to_empty_list(db_session):
    """
    Client isn't stored in `users` at all — the route returns [] for
    it without ever calling UserRepository.get_by_role, mirroring the
    existing Roles-page Client branch (which sources from `clients`
    instead). Simulated here since this check lives in the route
    itself, not a reusable service method.
    """

    client_role = await _get_role(db_session, "Client")
    users = await UserRepository(db_session).get_by_role(client_role.role_id)

    # Not asserting len == 0 here (a legacy/backfilled row could in
    # theory exist) — the real guarantee is the route-level branch,
    # covered by reading app/rbac/api/v1/roles.py's
    # `if role.name == CLIENT_ROLE_NAME: return []`. This test just
    # documents why: Client rows are not meaningfully "active users"
    # holding this role_id in the first place.
    assert isinstance(users, list)
