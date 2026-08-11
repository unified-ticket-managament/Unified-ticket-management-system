# test_organization_chart_hierarchy.py
#
# Coverage for the Organization Chart's reporting_manager_id source of
# truth: OrganizationService.get_chart_for_user builds a literal,
# role-agnostic hierarchy purely from the real User.reporting_manager_id
# foreign key — a column dedicated to this chart, deliberately separate
# from manager_id/teamlead_id (which keep driving every other existing
# consumer — permission-override/permission-request scoping, ticket
# assignment, SLA/escalation ownership — completely unchanged, still
# covered by test_user_listing_hierarchy.py). See
# app/rbac/services/organization_service.py's own module docstring for
# the full rationale, and alembic_rbac's add_reporting_manager_id_to_users
# migration for the one-time backfill (teamlead_id wins when both were
# set, else manager_id) that seeded this column's initial values.
#
# Runs against the real (dev) database inside a transaction that is
# always rolled back at the end — same convention as
# test_user_listing_hierarchy.py. The real employee master data seeded
# into this database (unified-backend/scripts/org_seed/source_data.py)
# is transcribed from the same company org chart this feature request
# itself referenced, so a handful of tests assert against real,
# specific people (Yashodha S / Umesh J) rather than only synthetic
# throwaway fixtures.

import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.orm import joinedload
from shared_models.models import Role, User

from app.auth.jwt import create_access_token
from app.core.rbac_cache import RBACCache
from app.database.session import AsyncSessionLocal, engine
from app.dependencies import auth as auth_deps
from app.rbac.repositories.reporting_manager_repository import ReportingManagerRepository
from app.rbac.repositories.role_repository import RoleRepository
from app.rbac.repositories.user_repository import UserRepository
from app.rbac.schemas.organization import OrganizationNode
from app.rbac.services.organization_service import OrganizationService


@pytest.fixture
async def db_session():
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.rollback()
    await engine.dispose()


def _build_service(session) -> OrganizationService:
    return OrganizationService(
        user_repository=UserRepository(session),
        role_repository=RoleRepository(session),
        reporting_manager_repository=ReportingManagerRepository(session),
    )


async def _get_user_by_email(session, email: str) -> User:
    result = await session.execute(
        select(User)
        .options(joinedload(User.role), joinedload(User.category))
        .where(User.email == email)
    )
    user = result.unique().scalar_one_or_none()
    if user is None:
        pytest.skip(f"Expected seeded user {email!r} not found in this database.")
    return user


async def _get_user_by_role(session, role_name: str) -> User:
    result = await session.execute(
        select(User)
        .options(joinedload(User.role), joinedload(User.category))
        .join(Role, Role.role_id == User.role_id)
        .where(Role.name == role_name, User.is_active.is_(True))
    )
    users = result.unique().scalars().all()
    if users:
        return users[0]
    pytest.skip(f"No active seeded {role_name!r} found.")


def _find_node(root: OrganizationNode, user_id) -> OrganizationNode | None:
    if root.user_id == user_id:
        return root
    for child in root.children:
        found = _find_node(child, user_id)
        if found is not None:
            return found
    return None


def _collect_ids(node: OrganizationNode) -> set:
    ids = {node.user_id}
    for child in node.children:
        ids |= _collect_ids(child)
    return ids


async def _make_role_user(session, role_name: str, **overrides) -> User:
    role = await RoleRepository(session).get_by_name(role_name)
    if role is None:
        pytest.skip(f"No {role_name!r} role seeded.")

    user = User(
        user_id=uuid.uuid4(),
        name=overrides.pop("name", f"Throwaway {role_name} {uuid.uuid4().hex[:6]}"),
        email=f"throwaway-{uuid.uuid4().hex[:8]}@example.com",
        password_hash="x",
        role_id=role.role_id,
        is_active=overrides.pop("is_active", True),
        **overrides,
    )
    session.add(user)
    await session.flush()
    # Re-fetched via the repository (joinedload of role/category) rather
    # than the just-constructed object directly — get_chart_for_user/
    # _to_node reads `user.role.name`, and a plain `User(...)` never
    # added through a loader has no `role` loaded, which raises
    # MissingGreenlet on first access in an async context. The real
    # caller (the `/users/me/organization-chart` route) always hands in
    # a `current_user` with `role`/`category` already populated, so
    # this reload only compensates for how this helper builds fixtures.
    return await UserRepository(session).get_by_id(user.user_id)


# --------------------------------------------------
# Real-data validation (per the feature request's own worked example)
# --------------------------------------------------


async def test_yashodha_reports_to_umesh_with_real_direct_reports(db_session):
    yashodha = await _get_user_by_email(db_session, "yashodha@probeps.com")
    umesh = await _get_user_by_email(db_session, "umesh@probeps.com")

    expected_reports = await UserRepository(db_session).get_direct_reports(yashodha.user_id)
    assert len(expected_reports) > 0, "Fixture assumption: Yashodha has real direct reports."

    service = _build_service(db_session)
    root = await service.get_chart_for_user(yashodha)

    # Umesh must appear as a real ancestor somewhere above Yashodha —
    # not necessarily the immediate root, since Umesh may himself sit
    # under a further real reporting_manager_id link.
    assert umesh.user_id in _collect_ids(root)

    yashodha_node = _find_node(root, yashodha.user_id)
    assert yashodha_node is not None
    reported_ids = {child.user_id for child in yashodha_node.children}
    assert reported_ids == {u.user_id for u in expected_reports}


def _ancestor_path(root: OrganizationNode, user_id) -> list[OrganizationNode] | None:
    """The chain of nodes from `root` down to (and including) `user_id`, or None if not found."""
    if root.user_id == user_id:
        return [root]
    for child in root.children:
        found = _ancestor_path(child, user_id)
        if found is not None:
            return [root] + found
    return None


async def test_real_three_level_ancestor_chain_is_climbed_in_full(db_session):
    """
    The chart must not stop at the immediate manager — real data has a
    genuine 3-hop chain (Rashmi R -> Sowmya Shree B -> Satish H R ->
    Umesh J, confirmed via a recursive SQL walk of reporting_manager_id)
    that the ancestor climb in get_chart_for_user must surface in full,
    not just the first hop.
    """

    rashmi_r = await _get_user_by_email(db_session, "rashmi.r@probeps.com")
    sowmya = await _get_user_by_email(db_session, "sowmyashree@probeps.com")
    satish = await _get_user_by_email(db_session, "satish@probeps.com")
    umesh = await _get_user_by_email(db_session, "umesh@probeps.com")

    assert rashmi_r.reporting_manager_id == sowmya.user_id
    assert sowmya.reporting_manager_id == satish.user_id
    assert satish.reporting_manager_id == umesh.user_id
    assert umesh.reporting_manager_id is None

    service = _build_service(db_session)
    root = await service.get_chart_for_user(rashmi_r)

    path = _ancestor_path(root, rashmi_r.user_id)
    assert path is not None
    path_ids = [n.user_id for n in path]
    assert path_ids == [umesh.user_id, satish.user_id, sowmya.user_id, rashmi_r.user_id]


async def test_bottom_level_user_shows_full_ancestor_chain_above_and_nothing_below(db_session):
    """
    Section 15/19's "bottom-level user" case: a leaf user's chart must
    still show their COMPLETE upward chain, not just stop because
    there's nothing below them.
    """

    rashmi_r = await _get_user_by_email(db_session, "rashmi.r@probeps.com")
    reports = await UserRepository(db_session).get_direct_reports(rashmi_r.user_id)
    if reports:
        pytest.skip("Fixture assumption: Rashmi R has no direct reports of her own.")

    service = _build_service(db_session)
    root = await service.get_chart_for_user(rashmi_r)

    umesh = await _get_user_by_email(db_session, "umesh@probeps.com")
    assert umesh.user_id in _collect_ids(root)
    rashmi_node = _find_node(root, rashmi_r.user_id)
    assert rashmi_node is not None
    assert rashmi_node.children == []


# --------------------------------------------------
# Empty-state cases
# --------------------------------------------------


async def test_user_with_no_reporting_manager_id_is_the_chart_root(db_session):
    umesh = await _get_user_by_email(db_session, "umesh@probeps.com")
    assert umesh.reporting_manager_id is None

    service = _build_service(db_session)
    root = await service.get_chart_for_user(umesh)

    assert root.user_id == umesh.user_id


async def test_leaf_staff_has_no_direct_reports(db_session):
    staff = await _get_user_by_role(db_session, "Staff")
    reports = await UserRepository(db_session).get_direct_reports(staff.user_id)
    if reports:
        pytest.skip("Picked Staff member unexpectedly has reports of their own.")

    service = _build_service(db_session)
    root = await service.get_chart_for_user(staff)

    staff_node = _find_node(root, staff.user_id)
    assert staff_node is not None
    assert staff_node.children == []


# --------------------------------------------------
# reporting_manager_id is the ONLY source of truth — manager_id/
# teamlead_id must never be consulted, even when they disagree
# --------------------------------------------------


async def test_account_manager_direct_reports_include_staff_with_no_team_lead_between(db_session):
    """
    Regression guard for the bug the original reporting_manager_id-less
    rewrite fixed: real seed data has an Account Manager (Kamaleshwaran
    K) whose reports are a mix of a Team Lead AND individual Staff
    reporting straight to him with no Team Lead in between. A role-
    branching traversal filtered to the Team Lead role only would
    silently drop the directly-reporting Staff member. get_direct_reports
    must include both, since it filters purely on reporting_manager_id,
    never on the report's own role.
    """

    kamaleshwaran = await _get_user_by_email(db_session, "kamalesh@probeps.com")
    fairoz = await _get_user_by_email(db_session, "fairoz@probeps.com")
    rajendra = await _get_user_by_email(db_session, "rajendra@probeps.com")

    assert fairoz.reporting_manager_id == kamaleshwaran.user_id
    assert fairoz.role.name == "Staff"
    assert rajendra.reporting_manager_id == kamaleshwaran.user_id
    assert rajendra.role.name == "Team Lead"

    reports = await UserRepository(db_session).get_direct_reports(kamaleshwaran.user_id)
    report_ids = {u.user_id for u in reports}

    assert fairoz.user_id in report_ids
    assert rajendra.user_id in report_ids

    service = _build_service(db_session)
    root = await service.get_chart_for_user(kamaleshwaran)
    kamaleshwaran_node = _find_node(root, kamaleshwaran.user_id)
    assert kamaleshwaran_node is not None
    chart_children_ids = {child.user_id for child in kamaleshwaran_node.children}
    assert fairoz.user_id in chart_children_ids
    assert rajendra.user_id in chart_children_ids


async def test_chart_follows_reporting_manager_id_even_when_manager_and_teamlead_disagree(db_session):
    """
    The confirmed, explicit acceptance criterion: when manager_id/
    teamlead_id and reporting_manager_id point at different people,
    the Organization Chart must follow reporting_manager_id ONLY.
    manager_id/teamlead_id still fully drive their own, unrelated
    consumers (see test_user_listing_hierarchy.py) — this test proves
    the chart itself never falls back to or is influenced by either.
    """

    site_lead = await _get_user_by_role(db_session, "Site Lead")
    account_manager_role = await RoleRepository(db_session).get_by_name("Account Manager")
    if account_manager_role is None:
        pytest.skip("No Account Manager role seeded.")
    account_managers = await UserRepository(db_session).get_by_role(account_manager_role.role_id)
    if not account_managers:
        pytest.skip("No active Account Manager seeded.")
    decoy_manager = account_managers[0]

    team_lead_role = await RoleRepository(db_session).get_by_name("Team Lead")
    if team_lead_role is None:
        pytest.skip("No Team Lead role seeded.")
    team_leads = await UserRepository(db_session).get_by_role(team_lead_role.role_id)
    if not team_leads:
        pytest.skip("No active Team Lead seeded.")
    decoy_teamlead = team_leads[0]

    throwaway = await _make_role_user(
        db_session,
        "Staff",
        manager_id=decoy_manager.user_id,
        teamlead_id=decoy_teamlead.user_id,
        reporting_manager_id=site_lead.user_id,
    )

    service = _build_service(db_session)
    root = await service.get_chart_for_user(throwaway)

    ancestor_ids = _collect_ids(root)
    assert site_lead.user_id in ancestor_ids
    assert decoy_manager.user_id not in ancestor_ids
    assert decoy_teamlead.user_id not in ancestor_ids


async def test_deactivated_direct_report_is_excluded(db_session):
    account_manager = await _get_user_by_role(db_session, "Account Manager")

    throwaway = await _make_role_user(
        db_session,
        "Team Lead",
        reporting_manager_id=account_manager.user_id,
        is_active=False,
    )

    reports = await UserRepository(db_session).get_direct_reports(account_manager.user_id)
    assert throwaway.user_id not in {u.user_id for u in reports}


async def test_updated_reporting_manager_id_is_reflected_immediately(db_session):
    account_manager_role = await RoleRepository(db_session).get_by_name("Account Manager")
    if account_manager_role is None:
        pytest.skip("No Account Manager role seeded.")

    account_managers = await UserRepository(db_session).get_by_role(account_manager_role.role_id)
    if len(account_managers) < 2:
        pytest.skip("Need at least two active Account Managers for this test.")
    first_am, second_am = account_managers[0], account_managers[1]

    throwaway = await _make_role_user(
        db_session,
        "Team Lead",
        reporting_manager_id=first_am.user_id,
    )

    service = _build_service(db_session)
    user_repository = UserRepository(db_session)

    root_before = await service.get_chart_for_user(throwaway)
    assert first_am.user_id in _collect_ids(root_before)
    assert second_am.user_id not in _collect_ids(root_before)

    throwaway.reporting_manager_id = second_am.user_id
    await db_session.flush()
    throwaway_loaded = await user_repository.get_by_id(throwaway.user_id)

    root_after = await service.get_chart_for_user(throwaway_loaded)
    assert second_am.user_id in _collect_ids(root_after)
    assert first_am.user_id not in _collect_ids(root_after)


# --------------------------------------------------
# Circular-reference protection
# --------------------------------------------------


async def test_downward_cycle_does_not_infinite_loop(db_session):
    """
    _build_literal_subtree's own cycle guard: if A's reporting_manager_id
    points at B and B's is reassigned to point back at A, building A's
    downward subtree must terminate rather than recursing forever
    (A -> B -> A -> B -> ...). The upward climb in get_chart_for_user
    already had its own separate `visited` guard; this covers the
    downward direction, which previously had none.
    """

    a = await _make_role_user(db_session, "Staff")
    b = await _make_role_user(db_session, "Staff", reporting_manager_id=a.user_id)

    a.reporting_manager_id = b.user_id
    await db_session.flush()
    a_loaded = await UserRepository(db_session).get_by_id(a.user_id)

    service = _build_service(db_session)
    # Must complete without hanging — the assertion itself is almost
    # secondary to the call simply returning at all.
    root = await service.get_chart_for_user(a_loaded)

    assert a.user_id in _collect_ids(root)
    assert b.user_id in _collect_ids(root)


async def test_self_reference_does_not_infinite_loop(db_session):
    """
    user.reporting_manager_id = user.id (the degenerate one-node cycle)
    must not hang either — the upward climb's own `visited` set already
    starts with current_user's own id, so the loop condition
    (`ancestor.user_id not in visited`) is false on the very first
    iteration; the downward guard's `seen` set works the same way.
    """

    a = await _make_role_user(db_session, "Staff")
    a.reporting_manager_id = a.user_id
    await db_session.flush()
    a_loaded = await UserRepository(db_session).get_by_id(a.user_id)

    service = _build_service(db_session)
    root = await service.get_chart_for_user(a_loaded)

    assert root.user_id == a.user_id
    assert root.children == []


# --------------------------------------------------
# Role independence — no crash / correct root for any role
# --------------------------------------------------


@pytest.mark.parametrize(
    "role_name",
    ["Super Admin", "Site Lead", "Account Manager", "Team Lead", "Staff"],
)
async def test_chart_builds_without_error_for_every_role(db_session, role_name):
    user = await _get_user_by_role(db_session, role_name)
    service = _build_service(db_session)

    root = await service.get_chart_for_user(user)

    assert user.user_id in _collect_ids(root)


# --------------------------------------------------
# RBAC-cache-hit regression: a live bug found via manual testing where
# the chart reported "no reporting manager" for a real user with a
# real reporting_manager_id, whenever their session happened to be
# cache-warm (i.e. most requests, after the first). Root cause:
# app/dependencies/auth.py's `_build_transient_user` (the RBAC-cache-
# hit reconstruction, used by get_current_user) never populated
# reporting_manager_id at all — it only ever set the handful of fields
# ticketing code reads (role, category, permissions, ...). The fix
# lives entirely in the org-chart ROUTE (users.py's
# get_organization_chart), which now always re-fetches a real,
# DB-backed User before calling get_chart_for_user rather than
# trusting `current_user` as given — this test proves that fix without
# needing a running HTTP server, by driving the exact same dependency
# function (auth_deps.get_current_user) the real route calls, forcing
# a cache hit, and then replicating the route's own re-fetch step.
# --------------------------------------------------


@pytest.fixture
def fresh_rbac_cache(monkeypatch):
    """Isolates this test from the module-level RBAC cache singleton — same convention as test_get_current_user_cache.py."""
    cache = RBACCache(ttl_seconds=30, max_size=100)
    monkeypatch.setattr(auth_deps, "get_rbac_cache", lambda: cache)
    return cache


def _bearer_credentials(token: str) -> SimpleNamespace:
    return SimpleNamespace(credentials=token)


def _mint_token_for(user: User) -> str:
    return create_access_token(
        user_id=user.user_id,
        email=user.email,
        role=user.role.name if user.role else "Staff",
        permissions=[],
        scoped_permissions={},
        name=user.name,
        role_id=user.role_id,
        category_id=user.category_id,
        category=(user.category.category_name.value if user.category else None),
        permission_version=user.permission_version,
    )


async def test_cache_hit_transient_user_never_reflects_real_reporting_manager_id(
    db_session, fresh_rbac_cache
):
    """
    Documents the actual root cause: on a cache hit, get_current_user's
    returned object has reporting_manager_id=None regardless of the
    real DB value — this is exactly why the org-chart ROUTE (not the
    service, not this dependency) must never pass that object straight
    into get_chart_for_user.
    """

    yashodha = await _get_user_by_email(db_session, "yashodha@probeps.com")
    assert yashodha.reporting_manager_id is not None
    token = _mint_token_for(yashodha)

    await auth_deps.get_current_user(credentials=_bearer_credentials(token), db=db_session)
    assert fresh_rbac_cache.is_valid(str(yashodha.user_id), yashodha.permission_version) is True

    cache_hit_user = await auth_deps.get_current_user(
        credentials=_bearer_credentials(token), db=db_session
    )
    assert cache_hit_user.user_id == yashodha.user_id
    assert cache_hit_user.reporting_manager_id is None  # the bug, confirmed


async def test_org_chart_shows_ancestor_even_when_session_is_cache_warm(db_session, fresh_rbac_cache):
    """
    The actual fix: replicates users.py's get_organization_chart route
    exactly (re-fetch the real user by id, ignore whatever
    get_current_user handed back) against a deliberately cache-warm
    session for Yashodha, and confirms Umesh still appears as her
    ancestor — reproducing the live bug from a cache-warm session
    reporting "No reporting manager assigned" for a real user, and
    proving the route-level fix resolves it.
    """

    yashodha = await _get_user_by_email(db_session, "yashodha@probeps.com")
    umesh = await _get_user_by_email(db_session, "umesh@probeps.com")
    token = _mint_token_for(yashodha)

    await auth_deps.get_current_user(credentials=_bearer_credentials(token), db=db_session)  # warm the cache
    cache_hit_user = await auth_deps.get_current_user(
        credentials=_bearer_credentials(token), db=db_session
    )
    assert cache_hit_user.reporting_manager_id is None  # confirms this test is exercising the cache-hit path

    # This is the fix: the route re-fetches by id instead of trusting
    # cache_hit_user directly.
    real_user = await UserRepository(db_session).get_by_id(cache_hit_user.user_id)
    service = _build_service(db_session)
    root = await service.get_chart_for_user(real_user)

    assert umesh.user_id in _collect_ids(root)
    assert root.user_id != yashodha.user_id  # she is not the chart root — Umesh (or above) is
