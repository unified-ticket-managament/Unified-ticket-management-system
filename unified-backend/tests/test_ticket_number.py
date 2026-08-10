# test_ticket_number.py
#
# Regression coverage for Issue 9 (human-readable "TKT-<n>" ticket
# reference): a persistent, sequential, never-renumbered
# `tickets.ticket_number` column backed by a real Postgres SEQUENCE
# (`ticket_number_seq`, added in alembic_ticketing's
# 277b41c65b53_add_ticket_number_sequence migration) — additional to,
# never a replacement for, the existing UUID `ticket_id` primary key.
#
# Runs against the real (dev) database. Most tests use a rolled-back
# transaction (same convention as test_ticket_status_on_assignment.py);
# the concurrency test necessarily commits real rows on separate
# connections (a single session can't be used concurrently, and the
# whole point is proving the real Postgres sequence is race-free
# across genuinely independent connections) — those rows are deleted
# again at the end of that test.

import asyncio
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import delete, select
from sqlalchemy.orm import joinedload
from shared_models.models import Role, User

from app.database.session import AsyncSessionLocal, engine
from app.ticketing.enums import TicketPriority
from app.ticketing.models.client import Client
from app.ticketing.models.ticket import Ticket
from app.ticketing.repositories.ticket_repository import (
    TicketRepository,
    parse_ticket_number_query,
)
from app.ticketing.schemas.ticket import TicketCreate


@pytest.fixture
async def db_session():
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.rollback()
    await engine.dispose()


async def _get_account_manager(session) -> User:
    result = await session.execute(
        select(User)
        .options(joinedload(User.role))
        .join(Role, Role.role_id == User.role_id)
        .where(Role.name == "Account Manager", User.is_active.is_(True))
    )
    users = result.unique().scalars().all()
    if users:
        return users[0]
    pytest.skip("No active seeded Account Manager found.")


async def _make_ticket(session, *, account_manager_id, title="Ticket number test ticket"):
    client = Client(
        client_id=uuid.uuid4(),
        name="Ticket Number Test Client",
        inbox_email=f"ticket-number-test-{uuid.uuid4().hex[:8]}@example.com",
        account_manager_id=account_manager_id,
        is_active=True,
    )
    session.add(client)
    await session.flush()

    repository = TicketRepository(session)
    ticket = await repository.create(
        TicketCreate(
            client_company_id=client.client_id,
            title=title,
            ticket_type="AR",
            current_priority=TicketPriority.MEDIUM,
        )
    )
    return client, ticket


# ---------------------------------------------------------------
# parse_ticket_number_query — pure logic, no DB.
# ---------------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("TKT-27", 27),
        ("tkt-27", 27),
        ("Tkt27", 27),
        ("TKT 27", 27),
        ("  tkt-1  ", 1),
        ("TKT-0001", 1),
    ],
)
def test_parse_ticket_number_query_recognizes_tkt_references(raw, expected):
    assert parse_ticket_number_query(raw) == expected


@pytest.mark.parametrize("raw", ["27", "insurance billing", "TKT", "TKT-", "TICKET-27", ""])
def test_parse_ticket_number_query_rejects_non_tkt_strings(raw):
    assert parse_ticket_number_query(raw) is None


# ---------------------------------------------------------------
# New tickets get a real, permanent, sequential number.
# ---------------------------------------------------------------


async def test_new_ticket_is_assigned_a_ticket_number(db_session):
    account_manager = await _get_account_manager(db_session)
    _client, ticket = await _make_ticket(db_session, account_manager_id=account_manager.user_id)

    assert isinstance(ticket.ticket_number, int)
    assert ticket.ticket_number > 0
    # UUID identity is completely untouched by this feature.
    assert isinstance(ticket.ticket_id, uuid.UUID)


async def test_ticket_numbers_increase_and_are_unique_across_creates(db_session):
    account_manager = await _get_account_manager(db_session)
    _client_a, ticket_a = await _make_ticket(db_session, account_manager_id=account_manager.user_id)
    _client_b, ticket_b = await _make_ticket(db_session, account_manager_id=account_manager.user_id)

    assert ticket_b.ticket_number > ticket_a.ticket_number
    assert ticket_a.ticket_number != ticket_b.ticket_number


async def test_ticket_number_never_changes_once_assigned(db_session):
    """
    Creating a later ticket must never renumber an earlier one — the
    core "stable, permanent reference" requirement.
    """

    account_manager = await _get_account_manager(db_session)
    _client_a, ticket_a = await _make_ticket(db_session, account_manager_id=account_manager.user_id)
    original_number = ticket_a.ticket_number

    # Create several more tickets after it.
    for _ in range(3):
        await _make_ticket(db_session, account_manager_id=account_manager.user_id)

    reloaded = await TicketRepository(db_session).get_by_id(ticket_a.ticket_id)
    assert reloaded.ticket_number == original_number


# ---------------------------------------------------------------
# Concurrency — the real Postgres sequence, not SELECT MAX(...)+1.
# ---------------------------------------------------------------


async def test_concurrent_ticket_creation_never_duplicates_numbers():
    """
    Five genuinely independent connections creating a ticket at the
    same time must all receive distinct ticket_numbers — this is what
    proves nextval() on a real Postgres sequence is used, not an
    in-app "read current max, add one" computation (which would race
    under exactly this scenario). A single shared session can't
    exercise this (it isn't safe to use concurrently, and would
    serialize the inserts anyway), so this test commits real rows on
    their own sessions/connections and deletes them again afterward.
    """

    async with AsyncSessionLocal() as setup_session:
        account_manager = await _get_account_manager(setup_session)
        client = Client(
            client_id=uuid.uuid4(),
            name="Concurrency Test Client",
            inbox_email=f"concurrency-test-{uuid.uuid4().hex[:8]}@example.com",
            account_manager_id=account_manager.user_id,
            is_active=True,
        )
        setup_session.add(client)
        await setup_session.commit()
        client_id = client.client_id

    async def _create_one():
        async with AsyncSessionLocal() as session:
            repository = TicketRepository(session)
            ticket = await repository.create(
                TicketCreate(
                    client_company_id=client_id,
                    title="Concurrent ticket-number test ticket",
                    ticket_type="AR",
                    current_priority=TicketPriority.MEDIUM,
                )
            )
            await session.commit()
            return ticket.ticket_id, ticket.ticket_number

    created: list[tuple] = []
    try:
        created = await asyncio.gather(*(_create_one() for _ in range(5)))
        numbers = [ticket_number for _ticket_id, ticket_number in created]
        assert len(set(numbers)) == len(numbers) == 5
    finally:
        async with AsyncSessionLocal() as cleanup_session:
            ticket_ids = [ticket_id for ticket_id, _ in created]
            if ticket_ids:
                await cleanup_session.execute(
                    delete(Ticket).where(Ticket.ticket_id.in_(ticket_ids))
                )
            await cleanup_session.execute(delete(Client).where(Client.client_id == client_id))
            await cleanup_session.commit()


# ---------------------------------------------------------------
# Search: TKT-<n> finds the exact ticket; UUID/title search unaffected.
# ---------------------------------------------------------------


async def test_search_by_tkt_reference_finds_the_correct_ticket(db_session):
    account_manager = await _get_account_manager(db_session)
    _client, ticket = await _make_ticket(
        db_session, account_manager_id=account_manager.user_id, title="Unique searchable title"
    )

    repository = TicketRepository(db_session)
    page = await repository.list_visible_page(
        account_manager_id=None,
        ticket_types=None,
        limit=50,
        offset=0,
        search=f"TKT-{ticket.ticket_number}",
    )

    matched_ids = {row[0].ticket_id for row in page.items}
    assert matched_ids == {ticket.ticket_id}


async def test_search_by_tkt_reference_is_case_insensitive(db_session):
    account_manager = await _get_account_manager(db_session)
    _client, ticket = await _make_ticket(db_session, account_manager_id=account_manager.user_id)

    repository = TicketRepository(db_session)
    page = await repository.list_visible_page(
        account_manager_id=None,
        ticket_types=None,
        limit=50,
        offset=0,
        search=f"tkt{ticket.ticket_number}",
    )

    matched_ids = {row[0].ticket_id for row in page.items}
    assert matched_ids == {ticket.ticket_id}


async def test_title_search_is_unaffected_by_tkt_support(db_session):
    account_manager = await _get_account_manager(db_session)
    unique_title = f"Distinctive-Title-{uuid.uuid4().hex[:8]}"
    _client, ticket = await _make_ticket(
        db_session, account_manager_id=account_manager.user_id, title=unique_title
    )

    repository = TicketRepository(db_session)
    page = await repository.list_visible_page(
        account_manager_id=None,
        ticket_types=None,
        limit=50,
        offset=0,
        search=unique_title,
    )

    matched_ids = {row[0].ticket_id for row in page.items}
    assert matched_ids == {ticket.ticket_id}


async def test_tkt_reference_maps_to_exactly_one_ticket(db_session):
    account_manager = await _get_account_manager(db_session)
    _client_a, ticket_a = await _make_ticket(db_session, account_manager_id=account_manager.user_id)
    _client_b, ticket_b = await _make_ticket(db_session, account_manager_id=account_manager.user_id)

    repository = TicketRepository(db_session)
    page = await repository.list_visible_page(
        account_manager_id=None,
        ticket_types=None,
        limit=50,
        offset=0,
        search=f"TKT-{ticket_a.ticket_number}",
    )

    assert len(page.items) == 1
    assert page.items[0][0].ticket_id == ticket_a.ticket_id
    assert page.items[0][0].ticket_id != ticket_b.ticket_id
