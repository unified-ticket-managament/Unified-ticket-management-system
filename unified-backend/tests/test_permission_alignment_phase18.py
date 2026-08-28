# test_permission_alignment_phase18.py
#
# Phase 18 (RBAC Enforcement Audit, BD-6/BD-11): implements the two
# permission-alignment changes Phase 17 traced but did not apply —
# ticket:create becomes the canonical permission for Create Ticket
# (superseding communication:convert_to_ticket, confirmed the same
# real-world capability under two names), and communication:create
# becomes the canonical gate for Compose specifically, split out from
# the broader communication:reply_external Reply/Reply All/Forward
# still use unchanged.
#
# Two groups of coverage:
# - Pure/unit (SimpleNamespace stand-ins, no DB) for the parameterized
#   access_control.ensure_can_compose_for_client/_category helpers —
#   these prove the two capabilities are genuinely separated (holding
#   one permission never satisfies the other) without needing a full
#   InteractionService construction.
# - DB-backed (real dev-database transaction, rolled back at the end,
#   same convention as test_inbox_ticket_service.py) for
#   InboxTicketService.create_ticket_from_interaction — proving
#   ticket:create is now required and the old communication:
#   convert_to_ticket permission alone no longer suffices, while every
#   pre-existing state/interaction-validation rule is untouched.
#
# Run individually if combined with other DB-touching test files, per
# this repo's documented pytest-asyncio event-loop-scope convention.

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import joinedload
from shared_models.models import Role, User

from app.database.session import AsyncSessionLocal, engine
from app.ticketing.enums import InteractionDirection, InteractionStatus, TicketPriority
from app.ticketing.models.client import Client
from app.ticketing.models.interaction import Interaction
from app.ticketing.repositories.client_repository import ClientRepository
from app.ticketing.repositories.interaction_repository import InteractionRepository
from app.ticketing.repositories.ticket_repository import TicketRepository
from app.ticketing.repositories.user_repository import UserRepository
from app.ticketing.schemas.ticket_from_interaction import TicketFromInteractionCreate
from app.ticketing.services.access_control import (
    ensure_can_compose_for_category,
    ensure_can_compose_for_client,
)
from app.ticketing.services.assignment_service import AssignmentService
from app.ticketing.services.inbox_ticket_service import InboxTicketService

TEAM_LEAD_CATEGORY = "Eligibility"


@pytest.fixture
async def db_session():
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.rollback()
    await engine.dispose()


async def _get_team_lead(session) -> User:
    result = await session.execute(
        select(User)
        .options(joinedload(User.role), joinedload(User.category))
        .join(Role, Role.role_id == User.role_id)
        .where(Role.name == "Team Lead", User.is_active.is_(True))
    )
    for user in result.unique().scalars().all():
        if user.category is not None and user.category.category_name == TEAM_LEAD_CATEGORY:
            return user
    pytest.skip(f"No active seeded Team Lead found for category {TEAM_LEAD_CATEGORY!r}.")


async def _make_client(session, *, account_manager_id) -> Client:
    client = Client(
        client_id=uuid.uuid4(),
        name="Phase 18 Test Client",
        inbox_email=f"phase18-test-{uuid.uuid4().hex[:8]}@example.com",
        account_manager_id=account_manager_id,
        is_active=True,
    )
    session.add(client)
    await session.flush()
    return client


async def _make_root_interaction(session, *, client_id, status: InteractionStatus) -> Interaction:
    interaction = Interaction(
        interaction_id=uuid.uuid4(),
        interaction_type="EMAIL",
        direction=InteractionDirection.OUTBOUND,
        status=status,
        payload={"message": "test"},
        parent_interaction_id=None,
        ticket_id=None,
        client_id=client_id,
        is_visible=True,
        subject="Test subject",
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


# ---------------------------------------------------------
# 1. ticket:create — Create Ticket, DB-backed
# ---------------------------------------------------------


async def test_create_ticket_denied_without_ticket_create(db_session):
    """The core regression: holding only the OLD permission
    (communication:convert_to_ticket) must no longer be sufficient —
    ticket:create is now the sole gate."""

    team_lead = await _get_team_lead(db_session)
    team_lead.permissions = ["communication:convert_to_ticket"]
    client = await _make_client(db_session, account_manager_id=team_lead.manager_id or team_lead.user_id)
    interaction = await _make_root_interaction(
        db_session, client_id=client.client_id, status=InteractionStatus.ASSIGNED
    )

    service = _build_inbox_ticket_service(db_session)
    with pytest.raises(HTTPException) as exc_info:
        await service.create_ticket_from_interaction(
            TicketFromInteractionCreate(
                interaction_id=interaction.interaction_id,
                title="Should be denied",
                ticket_type=TEAM_LEAD_CATEGORY,
                current_priority=TicketPriority.MEDIUM,
                agent_id=None,
            ),
            current_user=team_lead,
        )
    assert exc_info.value.status_code == 403


async def test_create_ticket_denied_with_no_permissions_at_all(db_session):
    """Direct backend request without ticket:create (or anything
    else) is denied — the un-authenticated-capability baseline."""

    team_lead = await _get_team_lead(db_session)
    team_lead.permissions = []
    client = await _make_client(db_session, account_manager_id=team_lead.manager_id or team_lead.user_id)
    interaction = await _make_root_interaction(
        db_session, client_id=client.client_id, status=InteractionStatus.ASSIGNED
    )

    service = _build_inbox_ticket_service(db_session)
    with pytest.raises(HTTPException) as exc_info:
        await service.create_ticket_from_interaction(
            TicketFromInteractionCreate(
                interaction_id=interaction.interaction_id,
                title="Should be denied",
                ticket_type=TEAM_LEAD_CATEGORY,
                current_priority=TicketPriority.MEDIUM,
                agent_id=None,
            ),
            current_user=team_lead,
        )
    assert exc_info.value.status_code == 403


async def test_create_ticket_allowed_with_ticket_create(db_session):
    """The positive case: ticket:create alone (no
    communication:convert_to_ticket at all) is sufficient."""

    team_lead = await _get_team_lead(db_session)
    team_lead.permissions = ["ticket:create"]
    client = await _make_client(db_session, account_manager_id=team_lead.manager_id or team_lead.user_id)
    interaction = await _make_root_interaction(
        db_session, client_id=client.client_id, status=InteractionStatus.ASSIGNED
    )

    service = _build_inbox_ticket_service(db_session)
    response = await service.create_ticket_from_interaction(
        TicketFromInteractionCreate(
            interaction_id=interaction.interaction_id,
            title="Should succeed",
            ticket_type=TEAM_LEAD_CATEGORY,
            current_priority=TicketPriority.MEDIUM,
            agent_id=None,
        ),
        current_user=team_lead,
    )

    assert response.ticket_id is not None
    ticket = await TicketRepository(db_session).get_by_id(response.ticket_id)
    assert ticket is not None
    assert ticket.client_company_id == client.client_id


async def test_create_ticket_still_rejects_already_ticketed_interaction_with_new_permission(db_session):
    """Existing interaction-validation rule (ticket_id already set)
    is untouched by the permission swap."""

    team_lead = await _get_team_lead(db_session)
    team_lead.permissions = ["ticket:create"]
    client = await _make_client(db_session, account_manager_id=team_lead.manager_id or team_lead.user_id)
    interaction = await _make_root_interaction(
        db_session, client_id=client.client_id, status=InteractionStatus.ASSIGNED
    )

    from app.ticketing.schemas.ticket import TicketCreate

    existing_ticket = await TicketRepository(db_session).create(
        TicketCreate(
            client_id=None,
            client_company_id=client.client_id,
            agent_id=None,
            created_by=team_lead.user_id,
            title="Pre-existing ticket",
            ticket_type=TEAM_LEAD_CATEGORY,
            current_priority=TicketPriority.MEDIUM,
        )
    )
    interaction.ticket_id = existing_ticket.ticket_id
    await db_session.flush()

    service = _build_inbox_ticket_service(db_session)
    with pytest.raises(HTTPException) as exc_info:
        await service.create_ticket_from_interaction(
            TicketFromInteractionCreate(
                interaction_id=interaction.interaction_id,
                title="Should be rejected — already ticketed",
                ticket_type=TEAM_LEAD_CATEGORY,
                current_priority=TicketPriority.MEDIUM,
                agent_id=None,
            ),
            current_user=team_lead,
        )
    assert exc_info.value.status_code == 400


# ---------------------------------------------------------
# 2. communication:create — Compose, unit-level (no DB)
#
# ensure_can_compose_for_client/_category are the real gate both
# compose_email (target: communication:create) and
# forward_to_internal_user/OutgoingMailService (unchanged default:
# communication:reply_external) call — testing them directly proves
# the two capabilities are genuinely separated without needing a full
# InteractionService/compose_email integration harness.
# ---------------------------------------------------------


def _user(role_name, user_id, permissions):
    return SimpleNamespace(
        role=SimpleNamespace(name=role_name),
        user_id=user_id,
        permissions=permissions,
    )


def _client(account_manager_id):
    return SimpleNamespace(account_manager_id=account_manager_id)


def test_compose_denies_reply_external_holder_without_create():
    """Holding communication:reply_external does NOT imply
    communication:create — Compose must not be silently granted by
    the broader Reply/Forward permission once the two are split."""

    am_id = uuid.uuid4()
    user = _user("Site Lead", uuid.uuid4(), ["communication:reply_external"])

    with pytest.raises(HTTPException) as exc_info:
        ensure_can_compose_for_client(
            _client(am_id), user, required_permission="communication:create"
        )
    assert exc_info.value.status_code == 403


def test_compose_allows_create_holder():
    """The positive case: communication:create alone is sufficient
    for a globally-unrestricted role."""

    user = _user("Site Lead", uuid.uuid4(), ["communication:create"])

    ensure_can_compose_for_client(
        _client(uuid.uuid4()), user, required_permission="communication:create"
    )  # must not raise


def test_compose_still_enforces_account_manager_client_ownership():
    """The permission split changes WHICH permission is required, not
    the pre-existing ownership rule layered on top of it."""

    am_id = uuid.uuid4()
    other_am_client = _client(uuid.uuid4())
    user = _user("Account Manager", am_id, ["communication:create"])

    with pytest.raises(HTTPException) as exc_info:
        ensure_can_compose_for_client(
            other_am_client, user, required_permission="communication:create"
        )
    assert exc_info.value.status_code == 403

    own_client = _client(am_id)
    ensure_can_compose_for_client(
        own_client, user, required_permission="communication:create"
    )  # must not raise — same AM owns this client


def test_forward_path_unaffected_default_still_reply_external():
    """forward_to_internal_user/OutgoingMailService never pass
    required_permission, so the default must remain
    communication:reply_external — Forward's behavior is byte-
    identical to before this phase."""

    user_with_reply_external = _user(
        "Site Lead", uuid.uuid4(), ["communication:reply_external"]
    )
    ensure_can_compose_for_client(
        _client(uuid.uuid4()), user_with_reply_external
    )  # must not raise — unchanged default

    user_with_only_create = _user("Site Lead", uuid.uuid4(), ["communication:create"])
    with pytest.raises(HTTPException) as exc_info:
        ensure_can_compose_for_client(_client(uuid.uuid4()), user_with_only_create)
    assert exc_info.value.status_code == 403


def test_create_does_not_grant_reply_external():
    """The other direction of the split: communication:create must
    not silently satisfy a communication:reply_external-gated call
    (Forward/legacy) either."""

    user = _user("Site Lead", uuid.uuid4(), ["communication:create"])

    with pytest.raises(HTTPException) as exc_info:
        ensure_can_compose_for_client(
            _client(uuid.uuid4()), user, required_permission="communication:reply_external"
        )
    assert exc_info.value.status_code == 403


class _FakeReportingManagerRepository:
    def __init__(self, account_manager_ids):
        self._ids = account_manager_ids

    async def list_account_manager_ids_by_category(self, category_id):
        return self._ids


async def test_compose_for_category_denies_reply_external_holder_without_create():
    am_id = uuid.uuid4()
    user = _user("Account Manager", am_id, ["communication:reply_external"])
    repo = _FakeReportingManagerRepository([am_id])

    with pytest.raises(HTTPException) as exc_info:
        await ensure_can_compose_for_category(
            SimpleNamespace(category_id=uuid.uuid4()),
            user,
            repo,
            required_permission="communication:create",
        )
    assert exc_info.value.status_code == 403


async def test_compose_for_category_allows_create_holder_who_is_reporting_manager():
    am_id = uuid.uuid4()
    user = _user("Account Manager", am_id, ["communication:create"])
    repo = _FakeReportingManagerRepository([am_id])

    await ensure_can_compose_for_category(
        SimpleNamespace(category_id=uuid.uuid4()),
        user,
        repo,
        required_permission="communication:create",
    )  # must not raise


async def test_compose_for_category_still_denies_non_reporting_manager():
    user = _user("Account Manager", uuid.uuid4(), ["communication:create"])
    repo = _FakeReportingManagerRepository([uuid.uuid4()])  # a different AM entirely

    with pytest.raises(HTTPException) as exc_info:
        await ensure_can_compose_for_category(
            SimpleNamespace(category_id=uuid.uuid4()),
            user,
            repo,
            required_permission="communication:create",
        )
    assert exc_info.value.status_code == 403
