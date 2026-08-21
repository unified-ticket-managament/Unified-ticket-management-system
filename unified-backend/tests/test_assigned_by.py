# test_assigned_by.py
#
# Regression coverage for the persisted Ticket.assigned_by column
# (root CLAUDE.md's "Assigned By" section) — the user who performed
# the assignment action that produced the ticket's CURRENT agent_id,
# stamped explicitly by every write path rather than derived at read
# time from the audit trail:
#
#   - InteractionService.claim_ticket -> TicketRepository.claim (a
#     self-assignment: assigned_by == the claimer, same as agent_id).
#   - InteractionService.transfer_agent (assigned_by == the actor
#     performing the transfer, deliberately NOT the new agent_id).
#   - InboxTicketService.create_ticket_from_interaction (a ticket born
#     already assigned via the "Assigned To" picker: assigned_by ==
#     the creator; left None when born unclaimed).
#
# Also covers the field's exposure on both API response shapes
# (TicketResponse via get_by_id, TicketListItemResponse via the
# paginated list_all/list_visible_page path — the ticket table's own
# data source) and the "existing ticket with no derivable history"
# case (a plain unclaimed ticket, or one created directly at the ORM
# level with no assignment at all, must read back assigned_by=None
# rather than crash or fabricate a value).
#
# Runs against the real (dev) database inside a transaction that is
# always rolled back at the end — same convention as
# test_ticket_status_on_assignment.py / test_transfer_agent_ownership.py.
# Category discovery is dynamic (not a hardcoded "Eligibility"-style
# constant) for the same reason test_ticket_status_on_assignment.py's
# own top-of-file comment explains: the shared dev database's
# role/category seeding has drifted over time.

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.orm import joinedload
from shared_models.models import Role, User

from app.database.session import AsyncSessionLocal, engine
from app.ticketing.enums import InteractionDirection, InteractionStatus, TicketPriority
from app.ticketing.models.client import Client
from app.ticketing.models.interaction import Interaction
from app.ticketing.models.ticket import Ticket
from app.ticketing.repositories.client_repository import ClientRepository
from app.ticketing.repositories.interaction_repository import InteractionRepository
from app.ticketing.repositories.ticket_repository import TicketRepository
from app.ticketing.repositories.user_repository import UserRepository
from app.ticketing.schemas.ticket_action import TransferAgentRequest
from app.ticketing.schemas.ticket_from_interaction import TicketFromInteractionCreate
from app.ticketing.services.assignment_service import AssignmentService
from app.ticketing.services.inbox_ticket_service import InboxTicketService
from app.ticketing.services.interaction_service import InteractionService
from app.ticketing.services.ticket_service import TicketService


@pytest.fixture
async def db_session():
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.rollback()
    await engine.dispose()


async def _find_team_lead_with_staff(session, staff_count: int) -> tuple[User, list[User]]:
    team_lead_result = await session.execute(
        select(User)
        .options(joinedload(User.role), joinedload(User.category))
        .join(Role, Role.role_id == User.role_id)
        .where(Role.name == "Team Lead", User.is_active.is_(True))
    )
    team_leads = [
        user for user in team_lead_result.unique().scalars().all() if user.category is not None
    ]

    staff_result = await session.execute(
        select(User)
        .options(joinedload(User.role), joinedload(User.category))
        .join(Role, Role.role_id == User.role_id)
        .where(Role.name == "Staff", User.is_active.is_(True))
    )
    staff_by_category: dict[str, list[User]] = {}
    for user in staff_result.unique().scalars().all():
        if user.category is None:
            continue
        staff_by_category.setdefault(user.category.category_name, []).append(user)

    for team_lead in team_leads:
        candidates = staff_by_category.get(team_lead.category.category_name, [])
        if len(candidates) >= staff_count:
            return team_lead, candidates[:staff_count]

    pytest.skip(
        f"No category currently has both an active Team Lead and {staff_count} "
        "active Staff in the connected database."
    )


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


async def _make_ticket(
    session, *, account_manager_id, ticket_type, agent_id=None, assigned_by=None
) -> tuple[Client, Ticket]:
    client = Client(
        client_id=uuid.uuid4(),
        name="Assigned-By Test Client",
        inbox_email=f"assigned-by-test-{uuid.uuid4().hex[:8]}@example.com",
        account_manager_id=account_manager_id,
        is_active=True,
    )
    session.add(client)
    await session.flush()

    ticket = Ticket(
        ticket_id=uuid.uuid4(),
        client_company_id=client.client_id,
        agent_id=agent_id,
        assigned_by=assigned_by,
        title="Assigned-By regression test ticket",
        ticket_type=ticket_type,
        current_status="OPEN",
        current_priority=TicketPriority.MEDIUM,
        created_at=datetime.now(timezone.utc),
    )
    session.add(ticket)
    await session.flush()
    return client, ticket


def _build_interaction_service(session) -> InteractionService:
    return InteractionService(
        interaction_repository=InteractionRepository(session),
        ticket_repository=TicketRepository(session),
        user_repository=UserRepository(session),
        client_repository=ClientRepository(session),
    )


def _build_ticket_service(session) -> TicketService:
    return TicketService(
        ticket_repository=TicketRepository(session),
        user_repository=UserRepository(session),
        client_repository=ClientRepository(session),
    )


async def _reload_ticket(session, ticket_id) -> Ticket:
    return await TicketRepository(session).get_by_id(ticket_id)


# ---------------------------------------------------------------
# 1. New assignment via Claim — a self-assignment: assigned_by must
#    equal the claimer, same as agent_id.
# ---------------------------------------------------------------


async def test_claim_sets_assigned_by_to_the_claiming_agent(db_session):
    team_lead, [staff] = await _find_team_lead_with_staff(db_session, 1)
    _client, ticket = await _make_ticket(
        db_session,
        account_manager_id=team_lead.manager_id or team_lead.user_id,
        ticket_type=staff.category.category_name,
    )

    service = _build_interaction_service(db_session)
    await service.claim_ticket(ticket.ticket_id, staff)

    reloaded = await _reload_ticket(db_session, ticket.ticket_id)
    assert reloaded.agent_id == staff.user_id
    assert reloaded.assigned_by == staff.user_id


# ---------------------------------------------------------------
# 2. New assignment via ticket creation with a pre-selected assignee —
#    assigned_by must be the creator, not the assignee (they happen to
#    be the same user in this scenario, self-assignment at creation
#    time, but the column is stamped from the actor, never the
#    resolved agent_id).
# ---------------------------------------------------------------


async def _make_inbox_client(session, *, account_manager_id) -> Client:
    client = Client(
        client_id=uuid.uuid4(),
        name="Assigned-By Test Client (Inbox)",
        inbox_email=f"assigned-by-inbox-test-{uuid.uuid4().hex[:8]}@example.com",
        account_manager_id=account_manager_id,
        is_active=True,
    )
    session.add(client)
    await session.flush()
    return client


async def _make_pending_interaction(session, *, client_id) -> Interaction:
    interaction = Interaction(
        interaction_id=uuid.uuid4(),
        interaction_type="EMAIL",
        direction=InteractionDirection.INBOUND,
        status=InteractionStatus.PENDING,
        payload={"message": "test"},
        parent_interaction_id=None,
        ticket_id=None,
        client_id=client_id,
        is_visible=True,
        subject="Assigned-By test subject",
        received_at=datetime.now(timezone.utc),
    )
    session.add(interaction)
    await session.flush()
    return interaction


def _build_inbox_ticket_service(session) -> InboxTicketService:
    return InboxTicketService(
        ticket_repository=TicketRepository(session),
        interaction_repository=InteractionRepository(session),
        assignment_service=AssignmentService(UserRepository(session)),
        client_repository=ClientRepository(session),
    )


async def test_create_ticket_with_preassigned_agent_sets_assigned_by_to_creator(db_session):
    team_lead, _staff = await _find_team_lead_with_staff(db_session, 1)
    team_lead.permissions = ["communication:convert_to_ticket"]
    client = await _make_inbox_client(
        db_session, account_manager_id=team_lead.manager_id or team_lead.user_id
    )
    interaction = await _make_pending_interaction(db_session, client_id=client.client_id)

    service = _build_inbox_ticket_service(db_session)
    response = await service.create_ticket_from_interaction(
        TicketFromInteractionCreate(
            interaction_id=interaction.interaction_id,
            title="Pre-assigned-at-creation assigned-by test ticket",
            ticket_type=team_lead.category.category_name,
            current_priority=TicketPriority.MEDIUM,
            agent_id=team_lead.user_id,
        ),
        current_user=team_lead,
    )

    ticket = await _reload_ticket(db_session, response.ticket_id)
    assert ticket.agent_id == team_lead.user_id
    assert ticket.assigned_by == team_lead.user_id


async def test_create_ticket_without_agent_leaves_assigned_by_none(db_session):
    team_lead, _staff = await _find_team_lead_with_staff(db_session, 1)
    team_lead.permissions = ["communication:convert_to_ticket"]
    client = await _make_inbox_client(
        db_session, account_manager_id=team_lead.manager_id or team_lead.user_id
    )
    interaction = await _make_pending_interaction(db_session, client_id=client.client_id)

    service = _build_inbox_ticket_service(db_session)
    response = await service.create_ticket_from_interaction(
        TicketFromInteractionCreate(
            interaction_id=interaction.interaction_id,
            title="Unassigned-at-creation assigned-by test ticket",
            ticket_type=team_lead.category.category_name,
            current_priority=TicketPriority.MEDIUM,
            agent_id=None,
        ),
        current_user=team_lead,
    )

    ticket = await _reload_ticket(db_session, response.ticket_id)
    assert ticket.agent_id is None
    assert ticket.assigned_by is None


# ---------------------------------------------------------------
# 3. Reassignment via Transfer — assigned_by must become the actor who
#    performed the transfer, never the new agent_id (the two happen to
#    differ in every scenario below, unlike a self-transfer).
# ---------------------------------------------------------------


async def test_transfer_sets_assigned_by_to_the_transferring_actor_not_new_agent(db_session):
    team_lead, [staff_a, staff_b] = await _find_team_lead_with_staff(db_session, 2)
    _client, ticket = await _make_ticket(
        db_session,
        account_manager_id=team_lead.manager_id or team_lead.user_id,
        ticket_type=team_lead.category.category_name,
        agent_id=staff_a.user_id,
        assigned_by=staff_a.user_id,
    )

    service = _build_interaction_service(db_session)
    await service.transfer_agent(
        ticket.ticket_id,
        TransferAgentRequest(new_agent_id=staff_b.user_id, reason="Reassigning"),
        team_lead,
    )

    reloaded = await _reload_ticket(db_session, ticket.ticket_id)
    assert reloaded.agent_id == staff_b.user_id
    assert reloaded.assigned_by == team_lead.user_id
    assert reloaded.assigned_by != reloaded.agent_id


# ---------------------------------------------------------------
# 4. Full example scenario from the task's own spec: Hema assigns to
#    Raju (Assigned To: Raju, Assigned By: Hema), Hema reassigns to
#    Kiran (Assigned To: Kiran, Assigned By: Hema — same actor, so
#    Assigned By does NOT change), then a different actor (Koushik)
#    reassigns to Ravi (Assigned To: Ravi, Assigned By: Koushik).
# ---------------------------------------------------------------


async def test_assigned_by_chain_matches_hema_kiran_koushik_example(db_session):
    hema, [raju, kiran, ravi] = await _find_team_lead_with_staff(db_session, 3)
    koushik = await _get_user_by_role(db_session, "Site Lead")

    _client, ticket = await _make_ticket(
        db_session,
        account_manager_id=hema.manager_id or hema.user_id,
        ticket_type=hema.category.category_name,
    )

    service = _build_interaction_service(db_session)

    # Hema assigns -> Raju
    await service.transfer_agent(
        ticket.ticket_id,
        TransferAgentRequest(new_agent_id=raju.user_id, reason="Initial assignment"),
        hema,
    )
    reloaded = await _reload_ticket(db_session, ticket.ticket_id)
    assert reloaded.agent_id == raju.user_id
    assert reloaded.assigned_by == hema.user_id

    # Hema reassigns -> Kiran (same actor — Assigned By stays Hema)
    await service.transfer_agent(
        ticket.ticket_id,
        TransferAgentRequest(new_agent_id=kiran.user_id, reason="Reassigning"),
        hema,
    )
    reloaded = await _reload_ticket(db_session, ticket.ticket_id)
    assert reloaded.agent_id == kiran.user_id
    assert reloaded.assigned_by == hema.user_id

    # Koushik (a different actor) reassigns -> Ravi
    await service.transfer_agent(
        ticket.ticket_id,
        TransferAgentRequest(new_agent_id=ravi.user_id, reason="Escalation handoff"),
        koushik,
    )
    reloaded = await _reload_ticket(db_session, ticket.ticket_id)
    assert reloaded.agent_id == ravi.user_id
    assert reloaded.assigned_by == koushik.user_id


# ---------------------------------------------------------------
# 5. Existing tickets with no derivable assignment history must read
#    back assigned_by=None rather than crash or fabricate a value —
#    covers both a genuinely-unclaimed ticket and one whose agent_id
#    was set with no assignment action at all (e.g. pre-migration
#    data the backfill couldn't confidently attribute).
# ---------------------------------------------------------------


async def test_unclaimed_ticket_has_no_assigned_by(db_session):
    team_lead, _staff = await _find_team_lead_with_staff(db_session, 1)
    _client, ticket = await _make_ticket(
        db_session,
        account_manager_id=team_lead.manager_id or team_lead.user_id,
        ticket_type=team_lead.category.category_name,
    )

    reloaded = await _reload_ticket(db_session, ticket.ticket_id)
    assert reloaded.agent_id is None
    assert reloaded.assigned_by is None


async def test_ticket_with_agent_but_no_assignment_history_has_no_assigned_by(db_session):
    team_lead, [staff] = await _find_team_lead_with_staff(db_session, 1)
    _client, ticket = await _make_ticket(
        db_session,
        account_manager_id=team_lead.manager_id or team_lead.user_id,
        ticket_type=team_lead.category.category_name,
        agent_id=staff.user_id,
        # assigned_by deliberately omitted — the exact "existing
        # ticket, no history" case the migration's nullable/default
        # column has to handle safely.
    )

    reloaded = await _reload_ticket(db_session, ticket.ticket_id)
    assert reloaded.agent_id == staff.user_id
    assert reloaded.assigned_by is None


# ---------------------------------------------------------------
# 6. API response shape — both TicketResponse (detail, get_by_id) and
#    TicketListItemResponse (the ticket table's own paginated data
#    source, list_all's list_visible_page branch) must expose
#    assigned_by/assigned_by_name correctly.
# ---------------------------------------------------------------


async def test_ticket_detail_response_exposes_assigned_by(db_session):
    team_lead, [staff] = await _find_team_lead_with_staff(db_session, 1)
    _client, ticket = await _make_ticket(
        db_session,
        account_manager_id=team_lead.manager_id or team_lead.user_id,
        ticket_type=staff.category.category_name,
    )

    interaction_service = _build_interaction_service(db_session)
    await interaction_service.claim_ticket(ticket.ticket_id, staff)

    super_admin = await _get_user_by_role(db_session, "Super Admin")
    ticket_service = _build_ticket_service(db_session)
    response = await ticket_service.get_by_id(ticket.ticket_id, current_user=super_admin)

    assert response.assigned_by == staff.user_id
    assert response.assigned_by_name == staff.name


async def test_ticket_list_response_exposes_assigned_by(db_session):
    team_lead, [staff] = await _find_team_lead_with_staff(db_session, 1)
    _client, ticket = await _make_ticket(
        db_session,
        account_manager_id=team_lead.manager_id or team_lead.user_id,
        ticket_type=staff.category.category_name,
    )

    interaction_service = _build_interaction_service(db_session)
    await interaction_service.claim_ticket(ticket.ticket_id, staff)

    super_admin = await _get_user_by_role(db_session, "Super Admin")
    super_admin.permissions = ["ticket:view_own"]
    ticket_service = _build_ticket_service(db_session)

    items, _total = await ticket_service.list_all(
        super_admin, limit=200, offset=0, search=ticket.title
    )

    matching = [item for item in items if item.ticket_id == ticket.ticket_id]
    assert len(matching) == 1
    assert matching[0].assigned_by == staff.user_id
    assert matching[0].assigned_by_name == staff.name
