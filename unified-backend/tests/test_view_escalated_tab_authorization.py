# test_view_escalated_tab_authorization.py
#
# Regression coverage for the RBAC fix that removed
# ESCALATION_TAB_ROLE_NAMES's hardcoded role-name bypass from
# TicketService.list_all/count_by_view's "escalated" tab gate.
#
# Before this fix: `if view == "escalated" and current_user.role.name
# not in {"Account Manager", "Team Lead", "Site Lead", "Super Admin"}:
# check has_permission(...)` — meaning a member of one of those four
# roles saw the Escalated tab/badge regardless of whether their role
# actually held ticket:view_escalated, because role membership alone
# short-circuited the permission check before it was ever evaluated.
# Confirmed live: revoking ticket:view_escalated from Team Lead's role
# grants had zero effect on a real Team Lead's Escalated tab, because
# the permission check line never ran for that role.
#
# After this fix: `has_permission(current_user, "ticket:view_escalated")`
# is the sole authority for both call sites — see ticket_service.py's
# updated comments at the two changed sites for the exact diff.
#
# Two independent test strategies, matched to what each call site
# actually depends on:
#
# - list_all's gate (the first statement in the method, before any
#   repository/relationship access) is a pure early return — those
#   tests use bare, synthetic User/Role objects (mirroring
#   app/dependencies/auth.py's _build_transient_user, the same minimal
#   shape the real JWT-cache-hit path already constructs), no DB
#   session or real TicketRepository needed, isolating exactly the
#   changed line. A stubbed repository proves the gate, once passed,
#   doesn't itself alter the repository's answer.
#
# - count_by_view's gate runs AFTER a real repository call (it needs
#   the real pool/mine/all counts regardless of escalated-tab access),
#   so proving "forced to 0 without the permission" needs a nonzero
#   raw count to force away from. Getting a genuine nonzero escalated
#   count for all four roles would require fabricating a full
#   multi-level assignment-chain escalation reaching each role's level
#   (see test_assignment_chain_escalation.py) — real, but unrelated to
#   this fix, which only touches the gate itself, never the
#   ownership-chain machinery those other tests already cover. So:
#   a stubbed ticket_repository (returning a fixed nonzero sentinel
#   count) isolates exactly the service-layer force-to-zero logic this
#   fix changed, for all four roles, plus one real end-to-end DB
#   scenario (Team Lead, reusing the same proven ownership setup
#   test_view_escalated_permission.py already uses) for an authentic
#   sanity check against genuine data.
#
# Requirement-4-equivalent note (a personal override that DENIES a
# role-granted permission): not applicable to this RBAC model.
# PermissionResolverService.get_effective_permissions is a plain set
# union of role grants and active overrides with no "deny" polarity
# column anywhere, and PermissionOverrideService.grant() rejects a
# redundant grant outright — there is no way to construct "role grants
# it, but an override takes it away" in this system. Nothing to test.
#
# Runs against the real (dev) database inside a transaction that is
# always rolled back at the end, for the one DB-backed test — same
# convention as test_escalation_service.py/test_view_escalated_permission.py.
# Known pre-existing issue (see root CLAUDE.md): DB-touching test files
# hang if run in the same pytest process as another DB-touching file —
# run this file in isolation.

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.orm import joinedload, selectinload
from shared_models.models import Role, User

from app.database.session import AsyncSessionLocal, engine
from app.ticketing.enums import SLAClockStatus, TicketPriority
from app.ticketing.models.client import Client
from app.ticketing.models.resolution_sla import ResolutionSLA
from app.ticketing.models.ticket import Ticket
from app.ticketing.repositories.sla_policy_repository import SLAPolicyRepository
from app.ticketing.services.escalation_service import build_escalation_service
from app.ticketing.services.ticket_service import TicketService

# The four previously-hardcoded roles (ESCALATION_TAB_ROLE_NAMES) plus
# one role that was never on that allow-list, used only in the
# with-permission tests to demonstrate the fix's actual point: access
# is now identical regardless of role, driven purely by the permission
# (exactly what a personal override for a non-listed role would grant).
FORMERLY_HARDCODED_ROLES = ["Team Lead", "Account Manager", "Site Lead", "Super Admin"]
ROLE_NEVER_ON_OLD_ALLOW_LIST = "Staff"


def _make_synthetic_user(role_name: str, *, permissions: list[str]) -> User:
    """Bare, DB-free User — mirrors app/dependencies/auth.py's
    _build_transient_user, the same minimal shape the real JWT-cache-
    hit path already constructs from token claims. Safe to use without
    a DB session because the code under test either never touches the
    repository at all (list_all's early return) or only calls a stub
    repository we control (the with-permission cases below)."""

    user = User(
        user_id=uuid.uuid4(),
        name=f"Synthetic {role_name}",
        email=f"synthetic-{uuid.uuid4().hex[:8]}@example.com",
        is_active=True,
        is_on_leave=False,
        role_id=uuid.uuid4(),
        category_id=None,
        permission_version=1,
    )
    user.role = Role(role_id=user.role_id, name=role_name)
    user.categories = []
    user.permissions = permissions
    user.scoped_permissions = {}
    return user


class _StubTicketRepository:
    """Returns fixed, recognizable sentinel values so a test can tell
    "the gate let the real call through, unmodified" apart from "the
    gate short-circuited" without needing genuine ticket/escalation
    rows or real ownership-chain data — see this file's own header
    comment for why that's the right scope for this fix."""

    def __init__(self, *, escalated_count: int = 7):
        self._escalated_count = escalated_count

    async def list_all(self, **_kwargs):
        # Empty ticket list (so TicketService._attach_names has nothing
        # to resolve and never touches user_repository/client_repository,
        # both left as None below) with a distinctive nonzero total —
        # proves the real repository call happened and its answer
        # passed through untouched.
        return [], 42

    async def count_by_view(self, **_kwargs):
        return {
            "pool": 0,
            "mine": 0,
            "all": 0,
            "escalated": self._escalated_count,
        }


def _service_with_stub_repository(*, escalated_count: int = 7) -> TicketService:
    return TicketService(
        ticket_repository=_StubTicketRepository(escalated_count=escalated_count),
        user_repository=None,
        client_repository=None,
    )


def _bare_ticket_service() -> TicketService:
    return TicketService(ticket_repository=None, user_repository=None)


# ---------------------------------------------------------
# list_all — denied without the permission (requirements 2, 6, 8, 10, 12)
# ---------------------------------------------------------


@pytest.mark.parametrize("role_name", FORMERLY_HARDCODED_ROLES)
async def test_list_all_escalated_denied_without_permission(role_name):
    """Core regression: role membership alone — even for the four
    previously-hardcoded roles — is no longer sufficient. Lacking
    ticket:view_escalated always 'sees nothing' for the escalated
    view, matching the method's own documented convention, regardless
    of role. Uses a bare service (ticket_repository=None) — if the old
    role-name bypass were still present, this would raise an
    AttributeError from touching the None repository instead of
    returning cleanly, since a passing role would fall through to the
    real repository call.
    """

    user = _make_synthetic_user(role_name, permissions=[])
    service = _bare_ticket_service()

    rows, total = await service.list_all(current_user=user, view="escalated")

    assert rows == []
    assert total == 0


# ---------------------------------------------------------
# list_all — allowed with the permission (requirements 1, 3, 5, 7, 9, 11)
# ---------------------------------------------------------


@pytest.mark.parametrize(
    "role_name", FORMERLY_HARDCODED_ROLES + [ROLE_NEVER_ON_OLD_ALLOW_LIST]
)
async def test_list_all_escalated_gate_passes_with_permission(role_name):
    """Holding ticket:view_escalated is sufficient to pass the tab gate
    for every role, including one (Staff) never on the old hardcoded
    allow-list — proving the gate is now permission-only, exactly what
    a personal override would grant a non-listed role. Passing the
    gate means the stub repository's own sentinel total (42, never
    (0, 0)) comes back untouched."""

    user = _make_synthetic_user(role_name, permissions=["ticket:view_escalated"])
    service = _service_with_stub_repository()

    rows, total = await service.list_all(current_user=user, view="escalated")

    assert rows == []
    assert total == 42


# ---------------------------------------------------------
# count_by_view — forced to 0 without the permission, passed through with it
# ---------------------------------------------------------


@pytest.mark.parametrize("role_name", FORMERLY_HARDCODED_ROLES)
async def test_count_by_view_escalated_forced_to_zero_without_permission(role_name):
    """The stub repository reports a nonzero escalated count (7) for
    every role — proving the service-layer force-to-zero override is
    what zeroes it, not a naturally-empty result, and that it now
    fires for every role lacking the permission, not just roles
    outside the old hardcoded allow-list."""

    user = _make_synthetic_user(role_name, permissions=[])
    service = _service_with_stub_repository(escalated_count=7)

    counts = await service.count_by_view(current_user=user)

    assert counts["escalated"] == 0


@pytest.mark.parametrize(
    "role_name", FORMERLY_HARDCODED_ROLES + [ROLE_NEVER_ON_OLD_ALLOW_LIST]
)
async def test_count_by_view_escalated_passes_through_with_permission(role_name):
    """With the permission, the stub's real (nonzero) count is
    returned unmodified for every role — including Staff, never on
    the old hardcoded allow-list."""

    user = _make_synthetic_user(role_name, permissions=["ticket:view_escalated"])
    service = _service_with_stub_repository(escalated_count=7)

    counts = await service.count_by_view(current_user=user)

    assert counts["escalated"] == 7


# ---------------------------------------------------------
# One real end-to-end DB scenario (Team Lead) — requirement 13:
# existing filtering/query behavior is unchanged by this fix
# ---------------------------------------------------------


@pytest.fixture
async def db_session():
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.rollback()
    await engine.dispose()


async def _get_staff_with_category(session) -> User:
    result = await session.execute(
        select(User)
        .options(joinedload(User.role), selectinload(User.categories))
        .join(Role, Role.role_id == User.role_id)
        .where(Role.name == "Staff", User.is_active.is_(True))
    )
    for user in result.unique().scalars().all():
        if user.categories:
            return user
    pytest.skip("No active seeded Staff with a category found.")


async def _get_user_with_role_and_categories(session, user_id) -> User:
    result = await session.execute(
        select(User)
        .options(joinedload(User.role), selectinload(User.categories))
        .where(User.user_id == user_id)
    )
    return result.unique().scalar_one()


async def _make_real_scenario(session, *, agent_id, ticket_type, account_manager_id):
    client = Client(
        client_id=uuid.uuid4(),
        name="View-Escalated-Tab-Authorization Test Client",
        inbox_email=f"view-escalated-tab-test-{uuid.uuid4().hex[:8]}@example.com",
        account_manager_id=account_manager_id,
        is_active=True,
    )
    session.add(client)

    started_at = datetime.now(timezone.utc) - timedelta(hours=1)
    ticket = Ticket(
        ticket_id=uuid.uuid4(),
        client_company_id=client.client_id,
        agent_id=agent_id,
        title="View-escalated-tab-authorization regression test ticket",
        ticket_type=ticket_type,
        current_status="OPEN",
        current_priority=TicketPriority.MEDIUM,
        created_at=started_at,
    )
    session.add(ticket)
    await session.flush()

    medium_policy = await SLAPolicyRepository(session).get_by_priority(TicketPriority.MEDIUM)
    resolution_sla = ResolutionSLA(
        resolution_sla_id=uuid.uuid4(),
        ticket_id=ticket.ticket_id,
        client_id=client.client_id,
        priority=TicketPriority.MEDIUM,
        status=SLAClockStatus.RUNNING,
        started_at=started_at,
        due_at=started_at + timedelta(hours=3),
        active_target_minutes=medium_policy.resolution_target_minutes,
    )
    session.add(resolution_sla)
    await session.flush()
    return ticket


async def test_real_escalated_ticket_visibility_matches_permission_not_role(db_session):
    """End-to-end sanity check against genuine seeded data and a real
    escalation (via EscalationService.manual_escalate, unchanged by
    this fix): whichever real user the assignment-chain resolution
    (build_chain_owner_ids/_resolve_step — entirely unaffected by this
    fix) names as an owner sees the ticket under view="escalated"
    while holding ticket:view_escalated, and sees nothing once that
    permission is (simulated as) revoked — proving the row-level
    ownership/visibility query itself
    (TicketRepository._escalated_owner_condition, _visibility_conditions)
    is completely untouched by this fix; only the tab-open/count-
    zeroing gate around it changed.

    Deliberately does not assume which role ends up owning the
    escalation (a fresh ticket with no assignment history resolves
    straight to the Site Lead/Super Admin global-inbox fallback, not
    the ticket's own category's Team Lead — see build_chain_owner_ids/
    resolve_owners_for_chain) — it reads the real owner back off the
    created escalation instead, so this test stays correct regardless
    of exactly how that chain-resolution logic behaves (already
    covered in depth by test_assignment_chain_escalation.py).
    """

    from app.ticketing.repositories.client_repository import ClientRepository
    from app.ticketing.repositories.ticket_escalation_repository import (
        TicketEscalationRepository,
    )
    from app.ticketing.repositories.ticket_repository import TicketRepository
    from app.ticketing.repositories.user_repository import UserRepository

    staff_owner = await _get_staff_with_category(db_session)
    category_name = staff_owner.categories[0].category_name

    ticket = await _make_real_scenario(
        db_session,
        agent_id=staff_owner.user_id,
        ticket_type=category_name,
        account_manager_id=staff_owner.manager_id or staff_owner.user_id,
    )

    escalation_service = build_escalation_service(db_session)
    # manual_escalate's sole authorization criterion is ownership
    # (Ticket.agent_id), not any permission — unaffected by this fix.
    await escalation_service.manual_escalate(ticket.ticket_id, staff_owner)

    escalation_repository = TicketEscalationRepository(db_session)
    escalation = await escalation_repository.get_active_by_ticket_id(ticket.ticket_id)
    assert escalation is not None and escalation.owner_ids, (
        "Escalation must have at least one real owner for this test to be meaningful."
    )
    owner_id = next(iter(escalation.owner_ids))
    owner = await _get_user_with_role_and_categories(db_session, owner_id)

    service = TicketService(
        ticket_repository=TicketRepository(db_session),
        user_repository=UserRepository(db_session),
        client_repository=ClientRepository(db_session),
        ticket_escalation_repository=escalation_repository,
    )

    # limit= is required to exercise the real code path the actual
    # Escalated tab uses (TicketService.list_all forwards view/
    # viewer_user_id to the repository's list_visible_page — and thus
    # applies the strict owner_ids condition — only when limit is not
    # None; the unbounded no-limit mode used by list_all_interactions/
    # list_all_audit_logs never receives `view` at all).
    with_permission_kwargs = dict(current_user=owner, view="escalated", limit=50, offset=0)

    # With the permission: the real row shows up, and the real count
    # reflects it (>= 1 — not asserting an exact value, since the dev
    # DB may already have other escalations owned by this same user
    # from other test runs/manual testing).
    owner.permissions = ["ticket:view_escalated"]
    rows, total = await service.list_all(**with_permission_kwargs)
    assert any(t.ticket_id == ticket.ticket_id for t in rows)
    assert total >= 1

    counts = await service.count_by_view(current_user=owner)
    assert counts["escalated"] >= 1

    # Without the permission: same real, currently-owned escalation,
    # but now invisible via the escalated view/count — the fix's core
    # promise for a role that, under the old code, would have seen it
    # regardless (if this owner happens to be one of the four
    # previously-hardcoded roles).
    owner.permissions = []
    rows, total = await service.list_all(
        current_user=owner, view="escalated", limit=50, offset=0
    )
    assert rows == []
    assert total == 0

    counts = await service.count_by_view(current_user=owner)
    assert counts["escalated"] == 0
