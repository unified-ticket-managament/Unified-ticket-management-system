# test_client_category_filter.py
#
# Regression coverage for the "Clients filter also offers inbox-mail
# categories" feature (see root CLAUDE.md's Clients-filter section):
#
# 1. CategoryResponse now exposes `inbox_email` (previously omitted
#    entirely from GET /categories' response, even though the column
#    has existed on shared_models.models.Category all along) — a pure
#    schema check, no DB needed.
# 2. The new `ticket_type_filter` param added to
#    AuditLogRepository.list_visible_page (mirrored identically onto
#    TicketRepository.dashboard_stats and
#    InteractionRepository.list_visible_page — same one-line
#    `if ticket_type_filter is not None: conditions.append(Ticket.
#    ticket_type == ticket_type_filter)` pattern in all three) narrows
#    results to one category, independent of the pre-existing
#    `client_company_id_filter`.
#
# Same real-DB-rolled-back-transaction convention as
# test_escalation_service.py/test_interaction_threading.py (no separate
# test database configured for this project) — run this file in
# isolation per the root CLAUDE.md's known DB-test-fragility note.

import uuid
from datetime import datetime, timezone

import pytest
from shared_models.models import Category, User

from app.database.session import AsyncSessionLocal, engine
from app.ticketing.enums import ActorRole, AuditEntityType, AuditEventType, TicketPriority
from app.ticketing.models.audit_log import AuditLog
from app.ticketing.models.client import Client
from app.ticketing.models.ticket import Ticket
from app.ticketing.repositories.audit_log_repository import AuditLogRepository
from app.ticketing.repositories.category_repository import CategoryRepository
from app.ticketing.schemas.category import CategoryResponse


def test_category_response_exposes_inbox_email():
    with_mailbox = CategoryResponse(
        category_id=uuid.uuid4(), category_name="Credentialing", inbox_email="credentialing@example.com"
    )
    assert with_mailbox.inbox_email == "credentialing@example.com"

    without_mailbox = CategoryResponse(category_id=uuid.uuid4(), category_name="No Mailbox")
    assert without_mailbox.inbox_email is None


@pytest.fixture
async def db_session():
    # See test_interaction_threading.py's identical fixture for why
    # engine.dispose() is required here (pytest-asyncio's per-test
    # event loop vs. the module-level connection pool).
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.rollback()
    await engine.dispose()


async def _make_ticket_with_audit_log(session, *, ticket_type: str) -> Ticket:
    account_manager = (await session.execute(User.__table__.select().limit(1))).first()
    # Any existing user works as the audit log's actor/owning client's
    # account manager — this test only exercises category filtering,
    # not account-manager scoping, so the specific user doesn't matter.
    account_manager_id = account_manager.user_id

    client = Client(
        client_id=uuid.uuid4(),
        name=f"Category Filter Test Client {uuid.uuid4().hex[:8]}",
        inbox_email=f"category-filter-test-{uuid.uuid4().hex[:8]}@example.com",
        account_manager_id=account_manager_id,
        is_active=True,
    )
    session.add(client)

    ticket = Ticket(
        ticket_id=uuid.uuid4(),
        client_company_id=client.client_id,
        agent_id=None,
        title="Category filter test ticket",
        ticket_type=ticket_type,
        current_status="OPEN",
        current_priority=TicketPriority.MEDIUM,
        created_at=datetime.now(timezone.utc),
    )
    session.add(ticket)
    await session.flush()

    audit_log = AuditLog(
        audit_id=uuid.uuid4(),
        entity_type=AuditEntityType.TICKET,
        entity_id=ticket.ticket_id,
        event_type=AuditEventType.STATUS_CHANGED,
        actor_id=account_manager_id,
        actor_name="Test Actor",
        actor_role=ActorRole.AGENT,
        old_values=None,
        new_values=None,
        ticket_id=ticket.ticket_id,
    )
    session.add(audit_log)
    await session.flush()

    return ticket


async def test_audit_log_ticket_type_filter_narrows_to_matching_category(db_session):
    ticket_type = f"Test Category {uuid.uuid4().hex[:8]}"
    ticket = await _make_ticket_with_audit_log(db_session, ticket_type=ticket_type)

    repository = AuditLogRepository(db_session)

    matching_page = await repository.list_visible_page(
        account_manager_id=None,
        ticket_types=None,
        limit=10,
        ticket_type_filter=ticket_type,
    )
    matching_ticket_ids = {row[0].ticket_id for row in matching_page.items}
    assert ticket.ticket_id in matching_ticket_ids

    other_page = await repository.list_visible_page(
        account_manager_id=None,
        ticket_types=None,
        limit=10,
        ticket_type_filter=f"Some Other Category {uuid.uuid4().hex[:8]}",
    )
    other_ticket_ids = {row[0].ticket_id for row in other_page.items}
    assert ticket.ticket_id not in other_ticket_ids


# --- CategoryRepository.list_all(category_ids=...) -------------------
#
# Regression coverage for the "All Clients filter leaks other Account
# Managers' category shared inboxes" fix (see root CLAUDE.md's
# Organization Structure / reporting_manager_teams section): GET
# /categories?mine=true resolves an Account Manager's own category ids
# via ReportingManagerRepository, then filters here. These tests cover
# the SQL filter itself, independent of that resolution step (which is
# covered separately, without a DB, in test_category_mine_filter.py).


async def _make_category(session, name_prefix: str = "RM Filter Test") -> Category:
    category = Category(
        category_id=uuid.uuid4(),
        category_name=f"{name_prefix} {uuid.uuid4().hex[:8]}",
    )
    session.add(category)
    await session.flush()
    return category


async def test_category_repository_list_all_unfiltered_returns_everything(db_session):
    category = await _make_category(db_session)

    repository = CategoryRepository(db_session)
    all_categories = await repository.list_all()

    assert category.category_id in {c.category_id for c in all_categories}


async def test_category_repository_list_all_filters_by_category_ids(db_session):
    category_a = await _make_category(db_session, name_prefix="RM Filter A")
    category_b = await _make_category(db_session, name_prefix="RM Filter B")

    repository = CategoryRepository(db_session)
    filtered = await repository.list_all(category_ids=[category_a.category_id])

    filtered_ids = {c.category_id for c in filtered}
    assert category_a.category_id in filtered_ids
    assert category_b.category_id not in filtered_ids


async def test_category_repository_list_all_empty_category_ids_returns_nothing(db_session):
    await _make_category(db_session)

    repository = CategoryRepository(db_session)
    filtered = await repository.list_all(category_ids=[])

    assert filtered == []


async def test_category_repository_list_all_multiple_ids_no_duplication(db_session):
    category_a = await _make_category(db_session, name_prefix="RM Filter Multi A")
    category_b = await _make_category(db_session, name_prefix="RM Filter Multi B")

    repository = CategoryRepository(db_session)
    filtered = await repository.list_all(
        category_ids=[category_a.category_id, category_b.category_id]
    )

    filtered_ids = [c.category_id for c in filtered]
    assert filtered_ids.count(category_a.category_id) == 1
    assert filtered_ids.count(category_b.category_id) == 1
