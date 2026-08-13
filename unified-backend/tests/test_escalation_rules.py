# test_escalation_rules.py
#
# Pure, no-DB tests for the assignment-chain escalation routing (see
# root CLAUDE.md's "SLA & Escalation" section) — same style as
# test_sla_escalation_rules.py: resolvers only ever read already-loaded
# Python attributes (or a small hand-rolled fake repository), so plain
# unpersisted model instances are enough, no real database needed.

import uuid

from shared_models.models import Role, User

from app.ticketing.enums import (
    OWNER_ROLE_ASSIGNEE_CHAIN,
    OWNER_ROLE_REPORTING_MANAGER,
    OWNER_ROLE_SITE_LEAD_FALLBACK,
)
from app.ticketing.models.ticket import Ticket
from app.ticketing.services.escalation_rules import (
    build_chain_owner_ids,
    resolve_owners_for_chain,
)


def _ticket(*, agent_id=None, assigned_by=None, created_by=None) -> Ticket:
    return Ticket(
        ticket_id=uuid.uuid4(),
        agent_id=agent_id,
        assigned_by=assigned_by,
        created_by=created_by,
    )


def _user(*, role_name="Staff", reporting_manager_id=None) -> User:
    return User(
        user_id=uuid.uuid4(),
        role=Role(role_id=uuid.uuid4(), name=role_name),
        reporting_manager_id=reporting_manager_id,
    )


class _FakeAuditLogRepository:
    """Maps (agent_user_id) -> the actor_id who assigned them, per a fixed dict."""

    def __init__(self, prior_assigner_by_agent: dict[uuid.UUID, uuid.UUID]):
        self._by_agent = prior_assigner_by_agent

    async def find_prior_assigner(self, *, ticket_id, agent_user_id):
        return self._by_agent.get(agent_user_id)


class _FakeUserRepository:
    def __init__(self, users_by_id: dict[uuid.UUID, User]):
        self._by_id = users_by_id

    async def get_by_id(self, user_id):
        return self._by_id.get(user_id)


async def _no_fallback() -> set[uuid.UUID]:
    return set()


class TestBuildChainOwnerIds:
    async def test_unclaimed_ticket_chains_to_creator(self):
        creator = uuid.uuid4()
        ticket = _ticket(agent_id=None, created_by=creator)
        chain = await build_chain_owner_ids(ticket, _FakeAuditLogRepository({}))
        assert chain == [creator]

    async def test_unclaimed_ticket_with_no_creator_is_empty(self):
        ticket = _ticket(agent_id=None, created_by=None)
        chain = await build_chain_owner_ids(ticket, _FakeAuditLogRepository({}))
        assert chain == []

    async def test_flow_a_single_hop_assigner_who_is_also_the_creator(self):
        """Kamaleshwaran assigns directly to Pavana; he's also the ticket's creator."""

        pavana, kamaleshwaran = uuid.uuid4(), uuid.uuid4()
        ticket = _ticket(agent_id=pavana, assigned_by=kamaleshwaran, created_by=kamaleshwaran)
        chain = await build_chain_owner_ids(ticket, _FakeAuditLogRepository({}))
        assert chain == [kamaleshwaran]

    async def test_flow_b_two_hops_through_the_assignment_history(self):
        """Kamaleshwaran -> Yashodha (Team Lead) -> Pavana (Staff)."""

        pavana, yashodha, kamaleshwaran = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        ticket = _ticket(agent_id=pavana, assigned_by=yashodha, created_by=kamaleshwaran)
        audit_log_repository = _FakeAuditLogRepository({yashodha: kamaleshwaran})
        chain = await build_chain_owner_ids(ticket, audit_log_repository)
        assert chain == [yashodha, kamaleshwaran]

    async def test_self_created_and_self_assigned_ticket_has_no_chain(self):
        someone = uuid.uuid4()
        ticket = _ticket(agent_id=someone, assigned_by=someone, created_by=someone)
        chain = await build_chain_owner_ids(ticket, _FakeAuditLogRepository({}))
        assert chain == []

    async def test_dead_end_with_no_recorded_assigner_falls_back_to_creator(self):
        holder, creator = uuid.uuid4(), uuid.uuid4()
        ticket = _ticket(agent_id=holder, assigned_by=None, created_by=creator)
        chain = await build_chain_owner_ids(ticket, _FakeAuditLogRepository({}))
        assert chain == [creator]

    async def test_cycle_terminates_without_looping_forever(self):
        a, b = uuid.uuid4(), uuid.uuid4()
        ticket = _ticket(agent_id=a, assigned_by=b, created_by=None)
        # b was "assigned by" a, and a was "assigned by" b — a real ping-pong.
        audit_log_repository = _FakeAuditLogRepository({b: a, a: b})
        chain = await build_chain_owner_ids(ticket, audit_log_repository)
        assert chain == [b, a]


class TestResolveOwnersForChain:
    async def test_terminal_position_falls_back_to_site_lead(self):
        site_lead_id = uuid.uuid4()

        async def _fallback():
            return {site_lead_id}

        ticket = _ticket(agent_id=uuid.uuid4())
        owners = await resolve_owners_for_chain(
            ticket=ticket,
            chain_owner_ids=[],
            chain_position=0,
            user_repository=_FakeUserRepository({}),
            resolve_site_lead_fallback_ids=_fallback,
        )
        assert owners == {site_lead_id: OWNER_ROLE_SITE_LEAD_FALLBACK}

    async def test_flow_a_first_step_includes_assigner_and_distinct_reporting_manager(self):
        pavana, kamaleshwaran, satish = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        ticket = _ticket(agent_id=pavana)
        user_repository = _FakeUserRepository(
            {pavana: _user(role_name="Staff", reporting_manager_id=satish)}
        )
        owners = await resolve_owners_for_chain(
            ticket=ticket,
            chain_owner_ids=[kamaleshwaran],
            chain_position=0,
            user_repository=user_repository,
            resolve_site_lead_fallback_ids=_no_fallback,
        )
        assert owners == {
            kamaleshwaran: OWNER_ROLE_ASSIGNEE_CHAIN,
            satish: OWNER_ROLE_REPORTING_MANAGER,
        }

    async def test_flow_b_reporting_manager_dedupes_with_the_chain_assigner(self):
        pavana, yashodha = uuid.uuid4(), uuid.uuid4()
        ticket = _ticket(agent_id=pavana)
        user_repository = _FakeUserRepository(
            {pavana: _user(role_name="Staff", reporting_manager_id=yashodha)}
        )
        owners = await resolve_owners_for_chain(
            ticket=ticket,
            chain_owner_ids=[yashodha, uuid.uuid4()],
            chain_position=0,
            user_repository=user_repository,
            resolve_site_lead_fallback_ids=_no_fallback,
        )
        assert owners == {yashodha: OWNER_ROLE_ASSIGNEE_CHAIN}

    async def test_reporting_manager_never_reapplies_past_the_first_step(self):
        pavana, yashodha, kamaleshwaran, satish = (
            uuid.uuid4(),
            uuid.uuid4(),
            uuid.uuid4(),
            uuid.uuid4(),
        )
        ticket = _ticket(agent_id=pavana)
        user_repository = _FakeUserRepository(
            {pavana: _user(role_name="Staff", reporting_manager_id=satish)}
        )
        owners = await resolve_owners_for_chain(
            ticket=ticket,
            chain_owner_ids=[yashodha, kamaleshwaran],
            chain_position=1,
            user_repository=user_repository,
            resolve_site_lead_fallback_ids=_no_fallback,
        )
        assert owners == {kamaleshwaran: OWNER_ROLE_ASSIGNEE_CHAIN}

    async def test_non_staff_current_assignee_gets_no_reporting_manager_addition(self):
        team_lead_id, assigner = uuid.uuid4(), uuid.uuid4()
        ticket = _ticket(agent_id=team_lead_id)
        user_repository = _FakeUserRepository(
            {team_lead_id: _user(role_name="Team Lead", reporting_manager_id=uuid.uuid4())}
        )
        owners = await resolve_owners_for_chain(
            ticket=ticket,
            chain_owner_ids=[assigner],
            chain_position=0,
            user_repository=user_repository,
            resolve_site_lead_fallback_ids=_no_fallback,
        )
        assert owners == {assigner: OWNER_ROLE_ASSIGNEE_CHAIN}
