# test_communication_view_permission_rbac.py
#
# Pure-logic coverage (no DB) for the communication:view_all /
# communication:view_assigned RBAC fix — makes both permissions the
# actual, backend-enforced source of truth for communication
# visibility on both the list side (InboxService._resolve_scope /
# get_inbox, which get_folder_counts/get_view_counts also inherit) and
# the detail side (ensure_agent_can_view_ticket /
# ensure_agent_can_view_pending_interaction's view_only branches, used
# by OpenEmailService.get_email_details), while preserving Account
# Manager's client-ownership ceiling.
#
# Style mirrors test_category_mailbox_access_control.py /
# test_ticket_view_only_forwarded_access.py: hand-rolled fakes,
# monkeypatch for the lazily-imported ReportingManagerRepository, no
# conftest/fixtures, relies on pytest.ini's asyncio_mode=auto.

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.ticketing.enums import TicketPriority, TicketStatus
from app.ticketing.services.access_control import (
    ensure_account_manager_owns_ticket_client,
    ensure_agent_can_view_pending_interaction,
    ensure_agent_can_view_ticket,
    resolve_communication_visibility_tier,
)
from app.ticketing.services.inbox_service import InboxService
from app.ticketing.services.open_email_service import OpenEmailService


# --------------------------------------------------------------------
# Shared fakes
# --------------------------------------------------------------------


class _FakeRole:
    def __init__(self, name):
        self.name = name


class _FakeCategory:
    def __init__(self, category_name):
        self.category_name = category_name


class _FakeUser:
    def __init__(self, role_name, user_id=None, categories=(), permissions=None, scoped_permissions=None):
        self.user_id = user_id or uuid4()
        self.role = _FakeRole(role_name)
        self.categories = [_FakeCategory(c) for c in categories]
        self.permissions = permissions or []
        self.scoped_permissions = scoped_permissions or {}


class _FakeTicket:
    def __init__(self, ticket_type, client_company_id=None, agent_id=None):
        self.ticket_id = uuid4()
        self.ticket_type = ticket_type
        self.client_company_id = client_company_id
        self.agent_id = agent_id
        self.current_priority = TicketPriority.MEDIUM
        self.current_status = TicketStatus.OPEN


class _FakeInteraction:
    def __init__(self, client_id=None, category_id=None):
        self.client_id = client_id
        self.category_id = category_id


class _FakeOpenEmailInteraction:
    """Full attribute set OpenEmailService.get_email_details actually
    reads, for the one real end-to-end test of that method below."""

    def __init__(self, *, ticket_id, client_id=None, category_id=None):
        self.interaction_id = uuid4()
        self.ticket_id = ticket_id
        self.parent_interaction_id = None
        self.client_id = client_id
        self.category_id = category_id
        self.payload = {"subject": "Test subject", "body": "Test body"}
        self.claimed_by = None
        self.message_id = None
        self.received_at = datetime.now(timezone.utc)
        self.created_at = datetime.now(timezone.utc)
        self.status = "ASSIGNED"
        self.tags = []
        self.folder_id = None
        self.references = []
        self.in_reply_to_message_id = None


class _FakeDB:
    pass


class _FakeClientRepository:
    def __init__(self, owner_by_client=None):
        self.db = _FakeDB()
        self._owner_by_client = owner_by_client or {}

    async def get_by_id(self, client_id):
        owner = self._owner_by_client.get(client_id)
        if owner is None:
            return None
        return type("Client", (), {"account_manager_id": owner})()

    async def list_client_ids_by_account_manager(self, account_manager_id):
        return [
            client_id
            for client_id, owner in self._owner_by_client.items()
            if owner == account_manager_id
        ]


class _FakeInteractionRepo:
    """Minimal collaborator for InboxService — no DB."""

    def __init__(self):
        self.db = _FakeDB()

    async def list_inbox(self, **kwargs):
        return [], 0

    async def list_thread_summaries(self, ids):
        return {}


def _patch_reporting_manager_repo(monkeypatch, category_ids_by_am=None):
    class _Fake:
        def __init__(self, db):
            pass

        async def list_category_ids_by_account_manager(self, account_manager_id):
            return list((category_ids_by_am or {}).get(account_manager_id, []))

    monkeypatch.setattr(
        "app.rbac.repositories.reporting_manager_repository.ReportingManagerRepository",
        _Fake,
    )


VIEW_ALL_ONLY = ["communication:view_all"]
VIEW_ASSIGNED_ONLY = ["communication:view_assigned"]
BOTH = ["communication:view_all", "communication:view_assigned"]
NEITHER = []


# --------------------------------------------------------------------
# resolve_communication_visibility_tier
# --------------------------------------------------------------------


def test_tier_view_all_only():
    user = _FakeUser("Staff", permissions=VIEW_ALL_ONLY)
    assert resolve_communication_visibility_tier(user) == "all"


def test_tier_view_assigned_only():
    user = _FakeUser("Staff", permissions=VIEW_ASSIGNED_ONLY)
    assert resolve_communication_visibility_tier(user) == "assigned"


def test_tier_both_resolves_to_all():
    user = _FakeUser("Staff", permissions=BOTH)
    assert resolve_communication_visibility_tier(user) == "all"


def test_tier_neither_resolves_to_none():
    user = _FakeUser("Staff", permissions=NEITHER)
    assert resolve_communication_visibility_tier(user) == "none"


# --------------------------------------------------------------------
# InboxService._resolve_scope / get_inbox — the list side
# --------------------------------------------------------------------


async def _get_inbox_status(user):
    service = InboxService(interaction_repository=_FakeInteractionRepo())
    try:
        await service.get_inbox(user)
        return 200
    except HTTPException as exc:
        return exc.status_code


async def test_get_inbox_denies_neither_permission_for_every_role(monkeypatch):
    _patch_reporting_manager_repo(monkeypatch, {})
    for role in ("Site Lead", "Super Admin", "Account Manager", "Team Lead", "Staff"):
        user = _FakeUser(role, categories=["AR"], permissions=NEITHER)
        status_code = await _get_inbox_status(user)
        assert status_code == 403, f"{role} with neither permission should be denied"


async def test_get_inbox_allows_view_all_only_for_every_role(monkeypatch):
    _patch_reporting_manager_repo(monkeypatch, {})
    for role in ("Site Lead", "Super Admin", "Account Manager", "Team Lead", "Staff"):
        user = _FakeUser(role, categories=["AR"], permissions=VIEW_ALL_ONLY)
        status_code = await _get_inbox_status(user)
        assert status_code == 200, f"{role} holding only view_all should reach GET /inbox"


async def test_get_inbox_allows_view_assigned_only_for_every_role(monkeypatch):
    _patch_reporting_manager_repo(monkeypatch, {})
    for role in ("Site Lead", "Super Admin", "Account Manager", "Team Lead", "Staff"):
        user = _FakeUser(role, categories=["AR"], permissions=VIEW_ASSIGNED_ONLY)
        status_code = await _get_inbox_status(user)
        assert status_code == 200, f"{role} holding only view_assigned should reach GET /inbox"


async def test_resolve_scope_view_all_is_global_for_non_account_manager_roles(monkeypatch):
    """
    communication:view_all -> truly unrestricted (all five scope
    variables None) for every role except Account Manager, regardless
    of role name — this is the core fix: the permission itself now
    drives the scope, not role.
    """

    service = InboxService(interaction_repository=_FakeInteractionRepo())
    for role in ("Site Lead", "Super Admin", "Team Lead", "Staff"):
        user = _FakeUser(role, categories=["AR"], permissions=VIEW_ALL_ONLY)
        scope = await service._resolve_scope(user)
        assert scope == (None, None, None, None, None), f"{role} with view_all should be unrestricted"


async def test_resolve_scope_account_manager_scope_unaffected_by_tier(monkeypatch):
    """
    Account Manager's own-clients/reporting-categories ceiling applies
    identically whether they hold view_all, view_assigned, or both —
    the one documented business-rule exception, verified to actually
    hold under the new permission-driven logic.
    """

    am_id = uuid4()
    category_id = uuid4()
    _patch_reporting_manager_repo(monkeypatch, {am_id: [category_id]})
    service = InboxService(interaction_repository=_FakeInteractionRepo())

    scopes = []
    for perms in (VIEW_ALL_ONLY, VIEW_ASSIGNED_ONLY, BOTH):
        user = _FakeUser("Account Manager", user_id=am_id, permissions=perms)
        scopes.append(await service._resolve_scope(user))

    assert all(s == (am_id, None, None, None, [category_id]) for s in scopes)


async def test_resolve_scope_team_lead_and_staff_assigned_tier_is_category_pool(monkeypatch):
    """
    Team Lead and Staff both resolve communication:view_assigned to
    their own category's shared pool ("their team") — Staff was
    explicitly widened from "only tickets assigned to me" to match
    Team Lead per product decision.
    """

    service = InboxService(interaction_repository=_FakeInteractionRepo())
    for role in ("Team Lead", "Staff"):
        user = _FakeUser(role, categories=["AR", "Claims"], permissions=VIEW_ASSIGNED_ONLY)
        account_manager_id, ticket_types, assigned_agent_id, extra_ticket_ids, category_ids = (
            await service._resolve_scope(user)
        )
        assert account_manager_id is None
        assert set(ticket_types) == {"AR", "Claims"}
        assert assigned_agent_id is None
        assert category_ids is None


async def test_resolve_scope_staff_no_category_sees_nothing(monkeypatch):
    service = InboxService(interaction_repository=_FakeInteractionRepo())
    user = _FakeUser("Staff", categories=[], permissions=VIEW_ASSIGNED_ONLY)
    _, ticket_types, _, _, _ = await service._resolve_scope(user)
    assert ticket_types == ["__no_category__"]


async def test_resolve_scope_site_lead_super_admin_assigned_only_is_still_global(monkeypatch):
    """
    Edge case (not a normal state — both roles hold view_all by
    default): if either role is somehow granted ONLY view_assigned, no
    narrower business scope is defined for them anywhere else in the
    system, so they still resolve to global rather than an undefined
    restriction.
    """

    service = InboxService(interaction_repository=_FakeInteractionRepo())
    for role in ("Site Lead", "Super Admin"):
        user = _FakeUser(role, permissions=VIEW_ASSIGNED_ONLY)
        scope = await service._resolve_scope(user)
        assert scope == (None, None, None, None, None)


# --------------------------------------------------------------------
# ensure_agent_can_view_ticket(view_only=True) — the ticketed-detail side
# --------------------------------------------------------------------


def test_view_only_denies_neither_permission_regardless_of_category_match():
    ticket = _FakeTicket("AR")
    user = _FakeUser("Staff", categories=["AR"], permissions=NEITHER)
    with pytest.raises(HTTPException) as exc_info:
        ensure_agent_can_view_ticket(ticket, user, view_only=True)
    assert exc_info.value.status_code == 403


def test_view_only_view_all_is_global_for_team_lead_and_staff():
    ticket = _FakeTicket("Payment Posting")  # outside the viewer's own category
    for role in ("Team Lead", "Staff"):
        user = _FakeUser(role, categories=["AR"], permissions=VIEW_ALL_ONLY)
        ensure_agent_can_view_ticket(ticket, user, view_only=True)  # must not raise


def test_view_only_view_assigned_matches_own_category_for_team_lead_and_staff():
    ticket = _FakeTicket("AR")
    for role in ("Team Lead", "Staff"):
        user = _FakeUser(role, categories=["AR"], permissions=VIEW_ASSIGNED_ONLY)
        ensure_agent_can_view_ticket(ticket, user, view_only=True)  # must not raise


def test_view_only_view_assigned_denies_other_teams_category_for_team_lead_and_staff():
    ticket = _FakeTicket("Payment Posting")
    for role in ("Team Lead", "Staff"):
        user = _FakeUser(role, categories=["AR"], permissions=VIEW_ASSIGNED_ONLY)
        with pytest.raises(HTTPException) as exc_info:
            ensure_agent_can_view_ticket(ticket, user, view_only=True)
        assert exc_info.value.status_code == 403


def test_view_only_account_manager_unrestricted_from_this_function_regardless_of_tier():
    """
    ensure_agent_can_view_ticket never restricts Account Manager
    itself (no DB access here) — the ownership ceiling is enforced
    separately by the caller (see the OpenEmailService tests below).
    """

    ticket = _FakeTicket("Anything")
    for perms in (VIEW_ALL_ONLY, VIEW_ASSIGNED_ONLY, BOTH):
        user = _FakeUser("Account Manager", permissions=perms)
        ensure_agent_can_view_ticket(ticket, user, view_only=True)  # must not raise


def test_view_only_site_lead_super_admin_unrestricted_with_either_permission():
    ticket = _FakeTicket("Anything")
    for role in ("Site Lead", "Super Admin"):
        for perms in (VIEW_ALL_ONLY, VIEW_ASSIGNED_ONLY, BOTH):
            user = _FakeUser(role, permissions=perms)
            ensure_agent_can_view_ticket(ticket, user, view_only=True)  # must not raise


def test_view_only_scoped_ticket_editother_override_bypasses_tier_and_category():
    """
    An existing, unrelated mechanism (a ticket-scoped
    ticket:editother_ticket override) must keep working even for a
    caller holding neither communication permission — the whole point
    of that grant is a single, specific, approved exception.
    """

    ticket = _FakeTicket("Payment Posting")
    user = _FakeUser(
        "Staff",
        categories=["AR"],
        permissions=NEITHER,
        scoped_permissions={"ticket:editother_ticket": [str(ticket.ticket_id)]},
    )
    ensure_agent_can_view_ticket(ticket, user, view_only=True)  # must not raise


def test_view_only_action_call_sites_completely_unaffected():
    """
    Regression guard: every action call site (view_only=False, the
    default) never checks either communication permission — unchanged
    before/after this fix.
    """

    ticket = _FakeTicket("AR")
    user = _FakeUser("Staff", categories=["AR"], permissions=NEITHER)
    ensure_agent_can_view_ticket(ticket, user)  # must not raise (own category, no view_only)

    other_ticket = _FakeTicket("Payment Posting")
    with pytest.raises(HTTPException) as exc_info:
        ensure_agent_can_view_ticket(other_ticket, user)
    assert exc_info.value.status_code == 403


# --------------------------------------------------------------------
# ensure_agent_can_view_pending_interaction(view_only=True) — pre-ticket mail
# --------------------------------------------------------------------


async def test_pending_view_only_denies_neither_permission():
    interaction = _FakeInteraction(client_id=uuid4())
    user = _FakeUser("Account Manager", permissions=NEITHER)
    with pytest.raises(HTTPException) as exc_info:
        await ensure_agent_can_view_pending_interaction(
            interaction, user, _FakeClientRepository(), view_only=True
        )
    assert exc_info.value.status_code == 403


async def test_pending_view_only_view_all_is_global_for_team_lead_and_staff():
    """
    Pre-ticket mail was previously never reachable by Team Lead/Staff
    at all — communication:view_all now genuinely means "all
    communications in the system" for them too, matching the spec.
    """

    interaction = _FakeInteraction(client_id=uuid4())
    for role in ("Team Lead", "Staff"):
        user = _FakeUser(role, permissions=VIEW_ALL_ONLY)
        await ensure_agent_can_view_pending_interaction(
            interaction, user, _FakeClientRepository(), view_only=True
        )  # must not raise


async def test_pending_view_only_view_assigned_still_excludes_team_lead_and_staff():
    """
    tier "assigned" alone doesn't newly expose pending mail to Team
    Lead/Staff — a pending item has no ticket/assignment yet, so it
    was never part of either role's "team" scope and stays excluded by
    the pre-existing, unrelated business rule.
    """

    interaction = _FakeInteraction(client_id=uuid4())
    for role in ("Team Lead", "Staff"):
        user = _FakeUser(role, permissions=VIEW_ASSIGNED_ONLY)
        with pytest.raises(HTTPException) as exc_info:
            await ensure_agent_can_view_pending_interaction(
                interaction, user, _FakeClientRepository(), view_only=True
            )
        assert exc_info.value.status_code == 403


async def test_pending_view_only_account_manager_ownership_enforced_under_either_tier():
    owner_id = uuid4()
    other_am_id = uuid4()
    client_id = uuid4()
    client_repo = _FakeClientRepository({client_id: owner_id})
    interaction = _FakeInteraction(client_id=client_id)

    for perms in (VIEW_ALL_ONLY, VIEW_ASSIGNED_ONLY, BOTH):
        owner = _FakeUser("Account Manager", user_id=owner_id, permissions=perms)
        await ensure_agent_can_view_pending_interaction(
            interaction, owner, client_repo, view_only=True
        )  # must not raise

        other = _FakeUser("Account Manager", user_id=other_am_id, permissions=perms)
        with pytest.raises(HTTPException) as exc_info:
            await ensure_agent_can_view_pending_interaction(
                interaction, other, client_repo, view_only=True
            )
        assert exc_info.value.status_code == 403


async def test_pending_view_only_site_lead_super_admin_unrestricted_with_either_permission():
    interaction = _FakeInteraction(client_id=uuid4())
    for role in ("Site Lead", "Super Admin"):
        for perms in (VIEW_ALL_ONLY, VIEW_ASSIGNED_ONLY, BOTH):
            user = _FakeUser(role, permissions=perms)
            await ensure_agent_can_view_pending_interaction(
                interaction, user, _FakeClientRepository(), view_only=True
            )  # must not raise


async def test_pending_non_view_only_callers_completely_unaffected():
    """
    Regression guard: claim/archive/reply/tags/folder-assign never
    pass view_only — the plain GLOBAL_INBOX_ROLE_NAMES/permission_backed/
    ownership rule is byte-identical to before this fix.
    """

    interaction = _FakeInteraction(client_id=uuid4())
    user = _FakeUser("Team Lead", permissions=BOTH)
    with pytest.raises(HTTPException) as exc_info:
        await ensure_agent_can_view_pending_interaction(interaction, user, _FakeClientRepository())
    assert exc_info.value.status_code == 403


# --------------------------------------------------------------------
# OpenEmailService.get_email_details — Account Manager client-ownership fix
# --------------------------------------------------------------------


class _FakeTicketRepository:
    def __init__(self, ticket):
        self._ticket = ticket

    async def get_by_id(self, ticket_id):
        return self._ticket


class _FakeInteractionRepoForOpenEmail:
    def __init__(self, interaction):
        self._interaction = interaction

    async def get_by_id(self, interaction_id):
        return self._interaction

    async def find_thread_root(self, interaction_id):
        return None

    async def list_thread(self, interaction_id):
        return []


def _make_open_email_service(ticket, interaction, client_repository):
    return OpenEmailService(
        interaction_repository=_FakeInteractionRepoForOpenEmail(interaction),
        ticket_repository=_FakeTicketRepository(ticket),
        client_repository=client_repository,
    )


async def test_get_email_details_account_manager_denied_for_unowned_client_ticket():
    """
    The Finding #5 fix, exercised through the real, complete
    OpenEmailService.get_email_details call — not just the extracted
    helper functions. Before this fix, any Account Manager (holding
    either communication permission) could open any other Account
    Manager's client's ticket communications through this exact
    method; this must now 403.
    """

    owner_id = uuid4()
    other_am_id = uuid4()
    client_id = uuid4()
    ticket = _FakeTicket("AR", client_company_id=client_id)
    interaction = _FakeOpenEmailInteraction(ticket_id=ticket.ticket_id)
    client_repo = _FakeClientRepository({client_id: owner_id})

    service = _make_open_email_service(ticket, interaction, client_repo)
    other_am = _FakeUser("Account Manager", user_id=other_am_id, permissions=BOTH)

    with pytest.raises(HTTPException) as exc_info:
        await service.get_email_details(interaction.ticket_id, current_user=other_am, mark_read=False)
    assert exc_info.value.status_code == 403


async def test_get_email_details_account_manager_allowed_for_owned_client_ticket():
    owner_id = uuid4()
    client_id = uuid4()
    ticket = _FakeTicket("AR", client_company_id=client_id)
    interaction = _FakeOpenEmailInteraction(ticket_id=ticket.ticket_id)
    client_repo = _FakeClientRepository({client_id: owner_id})

    service = _make_open_email_service(ticket, interaction, client_repo)
    owner = _FakeUser("Account Manager", user_id=owner_id, permissions=BOTH)

    response = await service.get_email_details(interaction.ticket_id, current_user=owner, mark_read=False)
    assert response.ticket_id == ticket.ticket_id


async def test_get_email_details_denies_neither_permission_even_for_own_category():
    """
    End-to-end confirmation of Finding #3's fix through the real
    method: a Staff member holding NEITHER communication permission
    must be denied even for their own category's ticket.
    """

    ticket = _FakeTicket("AR")
    interaction = _FakeOpenEmailInteraction(ticket_id=ticket.ticket_id)
    service = _make_open_email_service(ticket, interaction, _FakeClientRepository())
    staff = _FakeUser("Staff", categories=["AR"], permissions=NEITHER)

    with pytest.raises(HTTPException) as exc_info:
        await service.get_email_details(interaction.ticket_id, current_user=staff, mark_read=False)
    assert exc_info.value.status_code == 403


async def test_ensure_account_manager_owns_ticket_client_directly():
    """
    Direct coverage of the exact function OpenEmailService now calls —
    confirms it 403s for a non-owning Account Manager and passes for
    the owner, independent of any communication permission (it's a
    plain ownership check with no permission awareness of its own).
    """

    owner_id = uuid4()
    other_id = uuid4()
    client_id = uuid4()
    ticket = _FakeTicket("AR", client_company_id=client_id)
    client_repo = _FakeClientRepository({client_id: owner_id})

    owner = _FakeUser("Account Manager", user_id=owner_id)
    await ensure_account_manager_owns_ticket_client(ticket, owner, client_repo)  # must not raise

    other = _FakeUser("Account Manager", user_id=other_id)
    with pytest.raises(HTTPException) as exc_info:
        await ensure_account_manager_owns_ticket_client(ticket, other, client_repo)
    assert exc_info.value.status_code == 403


# --------------------------------------------------------------------
# Section 8 permutation matrix — A-F scenarios x the 4 user types
# --------------------------------------------------------------------
# Exercised against ensure_agent_can_view_ticket(view_only=True) for a
# Team Lead/Staff pair (the role whose "self" vs "own team" vs "other
# user" vs "other team" distinctions are meaningful) plus a dedicated
# Account Manager matrix for scenario F.


def test_matrix_view_all_only_sees_everything():
    self_ticket = _FakeTicket("AR")
    own_team_ticket = _FakeTicket("AR")
    other_team_ticket = _FakeTicket("Payment Posting")
    unassigned_ticket = _FakeTicket("Payment Posting")

    user = _FakeUser("Staff", categories=["AR"], permissions=VIEW_ALL_ONLY)
    for ticket in (self_ticket, own_team_ticket, other_team_ticket, unassigned_ticket):
        ensure_agent_can_view_ticket(ticket, user, view_only=True)  # all must PASS


def test_matrix_view_assigned_only_sees_own_team_denies_other_team():
    own_team_ticket = _FakeTicket("AR")
    other_team_ticket = _FakeTicket("Payment Posting")

    user = _FakeUser("Staff", categories=["AR"], permissions=VIEW_ASSIGNED_ONLY)
    ensure_agent_can_view_ticket(own_team_ticket, user, view_only=True)  # PASS

    with pytest.raises(HTTPException) as exc_info:
        ensure_agent_can_view_ticket(other_team_ticket, user, view_only=True)  # DENY
    assert exc_info.value.status_code == 403


def test_matrix_both_permissions_sees_everything():
    own_team_ticket = _FakeTicket("AR")
    other_team_ticket = _FakeTicket("Payment Posting")

    user = _FakeUser("Staff", categories=["AR"], permissions=BOTH)
    ensure_agent_can_view_ticket(own_team_ticket, user, view_only=True)  # PASS
    ensure_agent_can_view_ticket(other_team_ticket, user, view_only=True)  # PASS -- view_all wins


def test_matrix_neither_permission_denies_everything():
    own_team_ticket = _FakeTicket("AR")
    other_team_ticket = _FakeTicket("Payment Posting")

    user = _FakeUser("Staff", categories=["AR"], permissions=NEITHER)
    for ticket in (own_team_ticket, other_team_ticket):
        with pytest.raises(HTTPException) as exc_info:
            ensure_agent_can_view_ticket(ticket, user, view_only=True)  # DENY
        assert exc_info.value.status_code == 403
