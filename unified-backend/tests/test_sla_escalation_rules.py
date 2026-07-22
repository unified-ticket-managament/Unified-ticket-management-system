# test_sla_escalation_rules.py
#
# Pure recipient-resolution unit tests — no database needed, same
# no-DB / pytest.mark.parametrize / one-class-per-unit style as
# test_sla_clock_math.py. Resolvers only ever read already-loaded
# Python attributes (never issue their own queries), so plain
# unpersisted User/Role/Client instances are enough.

import uuid

import pytest
from shared_models.models import Role, User

from app.ticketing.models.client import Client
from app.ticketing.services.access_control import GLOBAL_INBOX_ROLE_NAMES
from app.ticketing.services.sla_escalation_rules import (
    FIRST_RESPONSE_RULES,
    RECIPIENT_RESOLVERS,
    RESOLUTION_RULES_CURRENT_OWNER,
    THRESHOLDS,
    RecipientContext,
    RecipientRole,
    resolve_account_manager,
    resolve_assigned_agent,
    resolve_current_owner,
    resolve_global_inbox,
    resolve_recipients,
    resolve_team_lead,
    resolve_team_members,
)


def _user(role_name: str, teamlead_id=None) -> User:
    return User(
        user_id=uuid.uuid4(),
        role=Role(role_id=uuid.uuid4(), name=role_name),
        teamlead_id=teamlead_id,
    )


def _client(account_manager_id) -> Client:
    return Client(client_id=uuid.uuid4(), account_manager_id=account_manager_id)


class TestResolveAccountManager:
    def test_no_client_resolves_to_nobody(self):
        ctx = RecipientContext(client=None)
        assert resolve_account_manager(ctx) == set()

    def test_client_present_resolves_to_its_account_manager(self):
        am_id = uuid.uuid4()
        ctx = RecipientContext(client=_client(am_id))
        assert resolve_account_manager(ctx) == {am_id}


class TestResolveTeamLead:
    def test_unclaimed_resolves_to_every_category_team_lead(self):
        tl1, tl2 = _user("Team Lead"), _user("Team Lead")
        ctx = RecipientContext(team_leads=[tl1, tl2])
        assert resolve_team_lead(ctx) == {tl1.user_id, tl2.user_id}

    def test_unclaimed_with_no_team_leads_resolves_to_nobody(self):
        ctx = RecipientContext(team_leads=[])
        assert resolve_team_lead(ctx) == set()

    def test_claimed_staff_assignee_resolves_to_their_own_teamlead(self):
        teamlead_id = uuid.uuid4()
        staff = _user("Staff", teamlead_id=teamlead_id)
        ctx = RecipientContext(assigned_agent=staff)
        assert resolve_team_lead(ctx) == {teamlead_id}

    def test_claimed_self_claimed_team_lead_resolves_to_themselves(self):
        team_lead = _user("Team Lead", teamlead_id=None)
        ctx = RecipientContext(assigned_agent=team_lead)
        assert resolve_team_lead(ctx) == {team_lead.user_id}

    def test_claimed_self_claimed_by_non_staff_non_teamlead_resolves_to_nobody(self):
        # claim_ticket applies no category gate — an Account Manager,
        # Site Lead, or Super Admin can self-claim directly, and none
        # of them have a "Team Lead" to notify.
        account_manager = _user("Account Manager", teamlead_id=None)
        ctx = RecipientContext(assigned_agent=account_manager)
        assert resolve_team_lead(ctx) == set()


class TestResolveTeamMembers:
    def test_resolves_every_given_team_member(self):
        staff1, staff2 = _user("Staff"), _user("Staff")
        ctx = RecipientContext(team_members=[staff1, staff2])
        assert resolve_team_members(ctx) == {staff1.user_id, staff2.user_id}

    def test_empty_team_resolves_to_nobody(self):
        ctx = RecipientContext(team_members=[])
        assert resolve_team_members(ctx) == set()


class TestResolveAssignedAgent:
    def test_no_assigned_agent_resolves_to_nobody(self):
        ctx = RecipientContext(assigned_agent=None)
        assert resolve_assigned_agent(ctx) == set()

    def test_assigned_agent_resolves_to_themselves(self):
        staff = _user("Staff")
        ctx = RecipientContext(assigned_agent=staff)
        assert resolve_assigned_agent(ctx) == {staff.user_id}


class TestResolveGlobalInbox:
    def test_passes_through_precomputed_ids(self):
        ids = {uuid.uuid4(), uuid.uuid4()}
        ctx = RecipientContext(global_inbox_ids=ids)
        assert resolve_global_inbox(ctx) == ids


class TestResolveRecipients:
    def test_unions_every_role_in_the_matched_tuple(self):
        am_id = uuid.uuid4()
        global_ids = {uuid.uuid4()}
        ctx = RecipientContext(client=_client(am_id), global_inbox_ids=global_ids)

        recipients = resolve_recipients(FIRST_RESPONSE_RULES, "BREACHED", ctx)

        assert recipients == {am_id} | global_ids

    def test_unknown_threshold_resolves_to_nobody_rather_than_raising(self):
        ctx = RecipientContext()
        assert resolve_recipients(FIRST_RESPONSE_RULES, "NOT_A_REAL_THRESHOLD", ctx) == set()


class TestFirstResponseAccountManagerNeverDropped:
    # The exact business fix this redesign was built for: the old
    # hardcoded if/elif dropped Account Manager at the Escalated tier
    # for First Response — the new table must keep them at every tier.
    @pytest.mark.parametrize("threshold", [name for name, _ in THRESHOLDS])
    def test_account_manager_present_at_every_threshold(self, threshold):
        assert RecipientRole.ACCOUNT_MANAGER in FIRST_RESPONSE_RULES[threshold]


class TestRuleTableCompleteness:
    # RESOLUTION_RULES_CURRENT_OWNER is deliberately partial (no
    # ESCALATED entry — see TestResolutionEscalatedHasNoRuleEntry
    # below), so only FIRST_RESPONSE_RULES is checked for full
    # threshold coverage here.
    @pytest.mark.parametrize("rules", [FIRST_RESPONSE_RULES])
    def test_every_threshold_has_a_rule_entry(self, rules):
        for name, _ in THRESHOLDS:
            assert name in rules

    @pytest.mark.parametrize("rules", [FIRST_RESPONSE_RULES, RESOLUTION_RULES_CURRENT_OWNER])
    def test_every_referenced_role_has_a_resolver(self, rules):
        for roles in rules.values():
            for role in roles:
                assert role in RECIPIENT_RESOLVERS


class TestResolveCurrentOwner:
    """
    Regression coverage for a real bug (2026-07-21, "current owner not
    receiving the SLA Breached notification"): resolve_current_owner
    used to return escalation_owner_ids unconditionally whenever any
    active escalation existed — even long after that escalation's
    acknowledger had accepted the ticket and handed it to someone else
    via claim/transfer/confirm-assignment. TicketEscalation.owner_ids is
    only ever refreshed by an explicit ladder advance (ack-timeout or
    handling-SLA-breach — see TicketEscalationRepository.advance), never
    by a plain accept-and-assign (EscalationService._complete_
    acceptance) — see test_escalation_service.py's
    test_escalation_owner_ids_are_not_refreshed_by_a_plain_acceptance
    for the data-level proof this staleness is real.
    """

    def test_no_escalation_unclaimed_resolves_to_team_pool(self):
        tl, staff = _user("Team Lead"), _user("Staff")
        ctx = RecipientContext(team_leads=[tl], team_members=[staff])
        assert resolve_current_owner(ctx) == {tl.user_id, staff.user_id}

    def test_no_escalation_claimed_resolves_to_assigned_agent(self):
        agent = _user("Staff")
        ctx = RecipientContext(assigned_agent=agent)
        assert resolve_current_owner(ctx) == {agent.user_id}

    def test_escalation_awaiting_acceptance_resolves_to_escalation_owner(self):
        # ACTIVE/ACKNOWLEDGED but nobody has actually taken the ticket
        # on yet — the accountable acknowledger is the right recipient,
        # even with a (stale, pre-escalation) assigned agent still on
        # the ticket record.
        team_lead_id = uuid.uuid4()
        stale_agent = _user("Staff")
        ctx = RecipientContext(
            assigned_agent=stale_agent,
            escalation_owner_ids={team_lead_id},
            escalation_acceptance_completed=False,
        )
        assert resolve_current_owner(ctx) == {team_lead_id}

    def test_escalation_accepted_resolves_to_new_assignee_not_the_acknowledger(self):
        # THE regression case: a Team Lead acknowledged and handed the
        # ticket to Staff X. escalation_owner_ids still says Team Lead
        # (never refreshed by a plain accept+assign), but the real
        # current owner — the one on the hook for the new, tighter
        # handling-stage deadline — is Staff X.
        team_lead_id = uuid.uuid4()
        staff_x = _user("Staff")
        ctx = RecipientContext(
            assigned_agent=staff_x,
            escalation_owner_ids={team_lead_id},
            escalation_acceptance_completed=True,
        )
        recipients = resolve_current_owner(ctx)
        assert recipients == {staff_x.user_id}
        assert team_lead_id not in recipients

    def test_escalation_accepted_with_no_assigned_agent_falls_back_to_escalation_owner(self):
        # Defensive edge case: acceptance completed but ticket.agent_id
        # somehow ended up None again — better to still notify someone
        # accountable than nobody.
        team_lead_id = uuid.uuid4()
        ctx = RecipientContext(
            assigned_agent=None,
            escalation_owner_ids={team_lead_id},
            escalation_acceptance_completed=True,
        )
        assert resolve_current_owner(ctx) == {team_lead_id}


class TestManagerScopeNeverBroadensBeyondTheOwningClient:
    """
    Regression coverage for the reported "Response SLA sent to all
    managers regardless of client/org scope" issue — investigated and
    NOT reproduced anywhere in this recipient-resolution code (every
    path here already resolves to exactly one client-owning manager, or
    to the fixed Site Lead/Super Admin overseer set, never a company-
    wide role query). Locking in the current, correct scoping so a
    future change can't silently widen it without a test failing.
    """

    def test_account_manager_resolves_to_exactly_one_client_owning_manager(self):
        owning_am = uuid.uuid4()
        some_other_clients_am = uuid.uuid4()  # must never appear
        ctx = RecipientContext(client=_client(owning_am))

        recipients = resolve_account_manager(ctx)

        assert recipients == {owning_am}
        assert some_other_clients_am not in recipients

    def test_global_inbox_role_set_excludes_account_manager_and_team_lead(self):
        assert GLOBAL_INBOX_ROLE_NAMES == {"Site Lead", "Super Admin"}
        assert "Account Manager" not in GLOBAL_INBOX_ROLE_NAMES
        assert "Team Lead" not in GLOBAL_INBOX_ROLE_NAMES

    def test_first_response_breached_resolves_to_owning_manager_and_global_inbox_only(self):
        owning_am = uuid.uuid4()
        global_ids = {uuid.uuid4(), uuid.uuid4()}
        ctx = RecipientContext(client=_client(owning_am), global_inbox_ids=global_ids)

        recipients = resolve_recipients(FIRST_RESPONSE_RULES, "BREACHED", ctx)

        assert recipients == {owning_am} | global_ids


class TestResolutionEscalatedHasNoRuleEntry:
    # Deliberate: Resolution SLA's ESCALATED (150%) tier sends no
    # notification at all (SLASweepService._notify_resolution skips it
    # outright) — the real escalation-created notification, fired
    # earlier at the crossing that first creates the TicketEscalation,
    # already covers it. A rule entry reappearing here would silently
    # reintroduce the redundant notification this was removed for.
    def test_escalated_is_absent(self):
        assert "ESCALATED" not in RESOLUTION_RULES_CURRENT_OWNER
