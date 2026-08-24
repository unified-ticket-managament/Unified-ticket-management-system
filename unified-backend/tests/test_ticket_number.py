# test_ticket_number.py
#
# Regression coverage for Issue 9 (human-readable "TKT-<n>" ticket
# reference) — additional to, never a replacement for, the existing
# UUID `ticket_id` primary key.
#
# `tickets.ticket_number` is now split across two independent numbering
# series, tagged by `ticket_number_series` (see Ticket's own docstring
# and the b201554c1537_add_ticket_number_series_and_counter migration):
# "legacy" tickets (everything that existed before that migration) keep
# whatever number they already had, sourced originally from
# `ticket_number_seq`; "current" tickets (everything created after)
# are numbered from TicketNumberCounter's gapless, transactional 1, 2,
# 3, ... — see TicketRepository._allocate_current_ticket_number. The
# same integer may legitimately appear once per series; uniqueness is
# enforced per-series (uq_tickets_ticket_number_series), not
# table-wide.
#
# Runs against the real (dev) database. Most tests use a rolled-back
# transaction (same convention as test_ticket_status_on_assignment.py);
# the concurrency and rollback tests necessarily commit/use real
# separate connections (a single session can't be used concurrently,
# and the whole point is proving the real locked counter is race-free
# and gap-free across genuinely independent connections) — those rows
# are deleted again afterward.

import asyncio
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import delete, select, text
from sqlalchemy.orm import joinedload
from shared_models.models import Role, User

from app.database.session import AsyncSessionLocal, engine
from app.ticketing.enums import TicketPriority, TicketStatus
from app.ticketing.models.client import Client
from app.ticketing.models.ticket import (
    TICKET_NUMBER_SERIES_CURRENT,
    TICKET_NUMBER_SERIES_LEGACY,
    Ticket,
)
from app.ticketing.models.ticket_number_counter import TicketNumberCounter
from app.ticketing.repositories.client_repository import ClientRepository
from app.ticketing.repositories.interaction_repository import InteractionRepository
from app.ticketing.repositories.ticket_repository import (
    TicketRepository,
    parse_ticket_number_query,
)
from app.ticketing.repositories.user_repository import UserRepository
from app.ticketing.schemas.ticket import TicketCreate
from app.ticketing.schemas.ticket_action import StatusChangeRequest, TransferAgentRequest
from app.ticketing.services.interaction_service import InteractionService


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


async def _get_site_lead(session) -> User:
    result = await session.execute(
        select(User)
        .options(joinedload(User.role))
        .join(Role, Role.role_id == User.role_id)
        .where(Role.name == "Site Lead", User.is_active.is_(True))
    )
    users = result.unique().scalars().all()
    if users:
        return users[0]
    pytest.skip("No active seeded Site Lead found.")


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
    same time must all receive distinct, and collectively CONTIGUOUS,
    "current"-series ticket_numbers — this is what proves
    TicketRepository._allocate_current_ticket_number's SELECT ... FOR
    UPDATE row lock genuinely serializes concurrent creators, rather
    than an in-app "read current max, add one" computation (which
    would race under exactly this scenario) or a bare SEQUENCE (which
    would only prove uniqueness, not gaplessness). A single shared
    session can't exercise this (it isn't safe to use concurrently,
    and would serialize the inserts anyway), so this test commits real
    rows on their own sessions/connections and deletes them again
    afterward.
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

        counter_before = (
            await setup_session.execute(
                select(TicketNumberCounter.next_number).where(
                    TicketNumberCounter.series == TICKET_NUMBER_SERIES_CURRENT
                )
            )
        ).scalar_one()

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
            return ticket.ticket_id, ticket.ticket_number, ticket.ticket_number_series

    created: list[tuple] = []
    try:
        created = await asyncio.gather(*(_create_one() for _ in range(5)))
        numbers = [ticket_number for _ticket_id, ticket_number, _series in created]
        series = {series for _ticket_id, _ticket_number, series in created}

        assert len(set(numbers)) == len(numbers) == 5
        assert series == {TICKET_NUMBER_SERIES_CURRENT}
        assert sorted(numbers) == list(range(counter_before, counter_before + 5))
    finally:
        async with AsyncSessionLocal() as cleanup_session:
            ticket_ids = [ticket_id for ticket_id, _, _ in created]
            if ticket_ids:
                await cleanup_session.execute(
                    delete(Ticket).where(Ticket.ticket_id.in_(ticket_ids))
                )
            await cleanup_session.execute(delete(Client).where(Client.client_id == client_id))
            await cleanup_session.commit()
        # Same convention as the db_session fixture's own teardown:
        # connections opened on THIS test's event loop must not linger
        # in the shared pool for the next test's (different) event loop
        # to try to reuse — pytest-asyncio's per-test event loop makes
        # that a guaranteed "Event loop is closed" failure, not a race.
        await engine.dispose()


async def test_failed_ticket_creation_never_burns_a_number():
    """
    Zero-gap requirement: if a ticket-creation transaction rolls back
    for any reason (mirrors app.database.session.get_db's own
    except-then-rollback behavior on a request-level failure), the
    "current" counter's increment must roll back with it — the next
    successful attempt must receive the SAME number, not skip past it.
    This is the whole reason the counter is a locked table row
    incremented in the same transaction as the ticket insert, rather
    than a Postgres SEQUENCE (whose nextval() is never rolled back).
    """

    async def _read_next_number(session) -> int:
        return (
            await session.execute(
                select(TicketNumberCounter.next_number).where(
                    TicketNumberCounter.series == TICKET_NUMBER_SERIES_CURRENT
                )
            )
        ).scalar_one()

    succeeding_ticket_id = None
    client_id = None
    try:
        async with AsyncSessionLocal() as setup_session:
            account_manager = await _get_account_manager(setup_session)
            client = Client(
                client_id=uuid.uuid4(),
                name="Rollback Test Client",
                inbox_email=f"rollback-test-{uuid.uuid4().hex[:8]}@example.com",
                account_manager_id=account_manager.user_id,
                is_active=True,
            )
            setup_session.add(client)
            await setup_session.commit()
            client_id = client.client_id

        # A creation attempt that never commits — e.g. a later failure
        # elsewhere in the same request would take this same path.
        # Read the counter's pre-attempt value on the SAME connection,
        # right before the attempt, rather than opening a separate one
        # just to read it.
        async with AsyncSessionLocal() as failing_session:
            next_number_before = await _read_next_number(failing_session)
            repository = TicketRepository(failing_session)
            failed_ticket = await repository.create(
                TicketCreate(
                    client_company_id=client_id,
                    title="Should never persist",
                    ticket_type="AR",
                    current_priority=TicketPriority.MEDIUM,
                )
            )
            assert failed_ticket.ticket_number == next_number_before
            await failing_session.rollback()

        # One fresh connection proves both halves: the rollback really
        # reverted the counter, AND the next successful attempt reclaims
        # that same number rather than skipping past it.
        async with AsyncSessionLocal() as verify_session:
            next_number_after_rollback = await _read_next_number(verify_session)
            assert next_number_after_rollback == next_number_before, (
                "A rolled-back ticket creation must not advance the counter — "
                f"expected {next_number_before}, got {next_number_after_rollback}"
            )

            repository = TicketRepository(verify_session)
            succeeding_ticket = await repository.create(
                TicketCreate(
                    client_company_id=client_id,
                    title="Should persist with the reclaimed number",
                    ticket_type="AR",
                    current_priority=TicketPriority.MEDIUM,
                )
            )
            succeeding_ticket_id = succeeding_ticket.ticket_id
            await verify_session.commit()
            assert succeeding_ticket.ticket_number == next_number_before
    finally:
        async with AsyncSessionLocal() as cleanup_session:
            if succeeding_ticket_id is not None:
                await cleanup_session.execute(
                    delete(Ticket).where(Ticket.ticket_id == succeeding_ticket_id)
                )
            if client_id is not None:
                await cleanup_session.execute(delete(Client).where(Client.client_id == client_id))
            await cleanup_session.commit()
        await engine.dispose()


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


async def test_tkt_reference_finds_the_right_ticket_among_matches(db_session):
    """
    Searching by ticket_a's number must always surface ticket_a, and
    never ticket_b (a different freshly-created ticket with a
    different number). This deliberately no longer asserts "exactly
    one result": since "current" and "legacy" tickets are independently
    numbered and may legitimately share an integer (see
    uq_tickets_ticket_number_series), a TKT-<n> search can legitimately
    return two rows — one per series — if a legacy ticket happens to
    hold the same number as a current one. What must never happen is
    the search missing the right ticket or returning the wrong one.
    """

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

    matched_ids = {row[0].ticket_id for row in page.items}
    assert ticket_a.ticket_id in matched_ids
    assert ticket_b.ticket_id not in matched_ids


# ---------------------------------------------------------------
# Whole-table invariants — guard the real, connected database's
# current state directly (same convention as
# test_attachment_upload_authorization.py's Staff/editother_ticket
# guard and test_employee_number.py's uniqueness guards), not just a
# freshly-created row in isolation. These are the tests that actually
# answer this task's "audit every existing ticket" requirement, and
# will keep answering it correctly as the table grows — they don't
# hardcode 187 or any other specific count.
# ---------------------------------------------------------------


async def test_no_duplicate_ticket_numbers_within_a_series(db_session):
    """
    Uniqueness is now scoped per ticket_number_series
    (uq_tickets_ticket_number_series), not table-wide — the same
    integer legitimately existing once in 'legacy' and once in
    'current' is expected and fine; two rows sharing BOTH the same
    number AND the same series is not, and would mean the DB
    constraint itself is missing/broken.
    """

    dupes = (
        await db_session.execute(
            text(
                "SELECT ticket_number, ticket_number_series, count(*) c FROM tickets "
                "GROUP BY ticket_number, ticket_number_series HAVING count(*) > 1"
            )
        )
    ).all()
    assert dupes == [], f"Duplicate (ticket_number, ticket_number_series) values found: {dupes}"


async def test_no_missing_or_malformed_ticket_numbers_in_database(db_session):
    row = (
        await db_session.execute(
            text(
                "SELECT count(*) AS without_number FROM tickets WHERE ticket_number IS NULL"
            )
        )
    ).one()
    assert row.without_number == 0

    row = (
        await db_session.execute(
            text(
                "SELECT count(*) AS malformed FROM tickets WHERE ticket_number IS NOT NULL AND ticket_number < 1"
            )
        )
    ).one()
    assert row.malformed == 0


async def test_every_existing_ticket_number_rank_matches_creation_order(db_session):
    """
    The real "audit the entire existing dataset" check: WITHIN EACH
    numbering series, every ticket's rank by ticket_number must equal
    its rank by (created_at ASC, ticket_id ASC) — the exact ordering
    277b41c65b53's own backfill used for 'legacy', and the order
    TicketNumberCounter's allocation naturally produces for 'current'.
    This is deliberately scoped per series (PARTITION BY
    ticket_number_series) rather than table-wide: 'current' tickets
    restart at 1 independently of 'legacy', so a whole-table rank
    comparison would (correctly) fail the moment any 'current' ticket
    exists. Not "zero gaps in 1..N" (legitimate ticket deletion breaks
    that on purpose — see the next test) — holds regardless of how
    many tickets have been created and later deleted in this shared
    dev database.
    """

    mismatches = (
        await db_session.execute(
            text(
                """
                WITH by_number AS (
                    SELECT ticket_id, ticket_number, ticket_number_series,
                           ROW_NUMBER() OVER (
                               PARTITION BY ticket_number_series ORDER BY ticket_number ASC
                           ) AS rank_by_number
                    FROM tickets
                ),
                by_creation AS (
                    SELECT ticket_id,
                           ROW_NUMBER() OVER (
                               PARTITION BY ticket_number_series ORDER BY created_at ASC, ticket_id ASC
                           ) AS rank_by_creation
                    FROM tickets
                )
                SELECT bn.ticket_id, bn.ticket_number, bn.ticket_number_series
                FROM by_number bn
                JOIN by_creation bc ON bn.ticket_id = bc.ticket_id
                WHERE bn.rank_by_number != bc.rank_by_creation
                """
            )
        )
    ).all()
    assert mismatches == [], f"ticket_number does not match creation order for: {mismatches}"


async def test_deleted_ticket_numbers_are_never_reused(db_session):
    """
    Part 12's explicit rule: once allocated (and committed), a
    ticket_number is permanently consumed, even if that ticket is later
    deleted. Proven directly: create a ticket, delete it, create
    another, and confirm TicketNumberCounter's 'current' row never
    rewinds to hand out the deleted ticket's number again — deletion
    never touches the counter at all, so this falls out of the
    allocation mechanism by construction, not something the
    application layer has to separately enforce.
    """

    account_manager = await _get_account_manager(db_session)
    _client_a, ticket_a = await _make_ticket(db_session, account_manager_id=account_manager.user_id)
    deleted_number = ticket_a.ticket_number

    await TicketRepository(db_session).delete(ticket_a)
    await db_session.flush()

    _client_b, ticket_b = await _make_ticket(db_session, account_manager_id=account_manager.user_id)
    assert ticket_b.ticket_number > deleted_number
    assert ticket_b.ticket_number != deleted_number


# ---------------------------------------------------------------
# Permanence across every lifecycle action this task explicitly lists.
# ---------------------------------------------------------------


def _build_interaction_service(session) -> InteractionService:
    return InteractionService(
        interaction_repository=InteractionRepository(session),
        ticket_repository=TicketRepository(session),
        user_repository=UserRepository(session),
        client_repository=ClientRepository(session),
    )


async def test_ticket_number_stable_through_full_lifecycle(db_session):
    site_lead = await _get_site_lead(db_session)
    site_lead.permissions = [
        "ticket:close_ticket", "ticket:reopen", "ticket:transfer", "ticket:update_status",
    ]
    account_manager = await _get_account_manager(db_session)

    _client, ticket = await _make_ticket(db_session, account_manager_id=account_manager.user_id)
    original_number = ticket.ticket_number

    service = _build_interaction_service(db_session)

    # Assignment / reassignment (transfer_agent).
    await service.transfer_agent(
        ticket.ticket_id,
        TransferAgentRequest(new_agent_id=site_lead.user_id, reason="ticket-number stability test"),
        site_lead,
    )
    reloaded = await TicketRepository(db_session).get_by_id(ticket.ticket_id)
    assert reloaded.ticket_number == original_number

    # Status change.
    await service.change_status(
        ticket.ticket_id,
        StatusChangeRequest(new_status=TicketStatus.RESOLVED),
        site_lead,
    )
    reloaded = await TicketRepository(db_session).get_by_id(ticket.ticket_id)
    assert reloaded.ticket_number == original_number

    # Close.
    await service.close_ticket(ticket.ticket_id, site_lead)
    reloaded = await TicketRepository(db_session).get_by_id(ticket.ticket_id)
    assert reloaded.ticket_number == original_number
    assert reloaded.current_status == TicketStatus.CLOSED

    # Reopen.
    await service.reopen_ticket(ticket.ticket_id, site_lead)
    reloaded = await TicketRepository(db_session).get_by_id(ticket.ticket_id)
    assert reloaded.ticket_number == original_number
    assert reloaded.current_status == TicketStatus.OPEN


# ---------------------------------------------------------------
# The tie-break rule the one-time backfill migration used
# (277b41c65b53_add_ticket_number_sequence.py) — validated directly
# against the exact SQL pattern it runs, since the migration itself
# isn't something a test re-invokes.
# ---------------------------------------------------------------


async def test_identical_created_at_ties_break_deterministically_by_ticket_id(db_session):
    account_manager = await _get_account_manager(db_session)
    client = Client(
        client_id=uuid.uuid4(),
        name="Tie-break Test Client",
        inbox_email=f"tie-break-test-{uuid.uuid4().hex[:8]}@example.com",
        account_manager_id=account_manager.user_id,
        is_active=True,
    )
    db_session.add(client)
    await db_session.flush()

    same_instant = datetime.now(timezone.utc) - timedelta(days=1)
    tickets = []
    for i in range(3):
        ticket = Ticket(
            ticket_id=uuid.uuid4(),
            client_company_id=client.client_id,
            title=f"Tie-break test ticket {i}",
            ticket_type="AR",
            current_priority=TicketPriority.MEDIUM,
            created_at=same_instant,
        )
        db_session.add(ticket)
        tickets.append(ticket)
    await db_session.flush()

    # Mirrors 277b41c65b53's own `ORDER BY created_at ASC, ticket_id ASC`
    # exactly, scoped to just these 3 identically-timestamped rows.
    ticket_ids = [t.ticket_id for t in tickets]
    result = await db_session.execute(
        select(Ticket.ticket_id)
        .where(Ticket.ticket_id.in_(ticket_ids))
        .order_by(Ticket.created_at.asc(), Ticket.ticket_id.asc())
    )
    actual_order = list(result.scalars().all())
    expected_order = sorted(ticket_ids)
    assert actual_order == expected_order, (
        "Tie-break for identical created_at values must order by ticket_id ASC, "
        f"expected {expected_order}, got {actual_order}"
    )


# ---------------------------------------------------------------
# The dual-series schema itself: the counter table exists and is
# seeded correctly, and the composite unique constraint enforces
# exactly the intended rule (forbidden within a series, legal across
# series) — not just "the app happens to behave this way today."
# ---------------------------------------------------------------


async def test_current_series_counter_row_exists_and_is_seeded(db_session):
    counter = (
        await db_session.execute(
            select(TicketNumberCounter).where(
                TicketNumberCounter.series == TICKET_NUMBER_SERIES_CURRENT
            )
        )
    ).scalar_one()
    assert counter.next_number >= 1


async def test_duplicate_ticket_number_within_same_series_is_rejected_by_the_db(db_session):
    """
    The composite constraint (ticket_number, ticket_number_series) must
    still reject two rows sharing BOTH values — exactly as strict as
    the single-column constraint it replaced, just scoped narrower.
    """

    account_manager = await _get_account_manager(db_session)
    client = Client(
        client_id=uuid.uuid4(),
        name="Duplicate-Within-Series Test Client",
        inbox_email=f"dup-within-series-{uuid.uuid4().hex[:8]}@example.com",
        account_manager_id=account_manager.user_id,
        is_active=True,
    )
    db_session.add(client)
    await db_session.flush()

    colliding_number = (
        await db_session.execute(
            select(TicketNumberCounter.next_number).where(
                TicketNumberCounter.series == TICKET_NUMBER_SERIES_CURRENT
            )
        )
    ).scalar_one()

    db_session.add(
        Ticket(
            ticket_id=uuid.uuid4(),
            client_company_id=client.client_id,
            title="First current-series ticket at this number",
            ticket_type="AR",
            current_priority=TicketPriority.MEDIUM,
            ticket_number=colliding_number,
            ticket_number_series=TICKET_NUMBER_SERIES_CURRENT,
        )
    )
    await db_session.flush()

    db_session.add(
        Ticket(
            ticket_id=uuid.uuid4(),
            client_company_id=client.client_id,
            title="Second current-series ticket at the SAME number",
            ticket_type="AR",
            current_priority=TicketPriority.MEDIUM,
            ticket_number=colliding_number,
            ticket_number_series=TICKET_NUMBER_SERIES_CURRENT,
        )
    )
    with pytest.raises(Exception):
        await db_session.flush()


async def test_current_ticket_can_legitimately_share_a_number_with_a_legacy_ticket(db_session):
    """
    The whole point of the dual-series design: a 'current' ticket and a
    'legacy' ticket ARE allowed to hold the identical integer, since
    uniqueness is scoped per series. Proven by directly constructing a
    synthetic 'legacy' row at whatever number the 'current' counter is
    about to hand out next, then creating a real ticket through the
    normal repository path — both must persist without a
    UniqueViolation, and the per-series duplicate check must not flag
    them.
    """

    account_manager = await _get_account_manager(db_session)
    client = Client(
        client_id=uuid.uuid4(),
        name="Cross-Series Collision Test Client",
        inbox_email=f"cross-series-{uuid.uuid4().hex[:8]}@example.com",
        account_manager_id=account_manager.user_id,
        is_active=True,
    )
    db_session.add(client)
    await db_session.flush()

    next_current_number = (
        await db_session.execute(
            select(TicketNumberCounter.next_number).where(
                TicketNumberCounter.series == TICKET_NUMBER_SERIES_CURRENT
            )
        )
    ).scalar_one()

    legacy_ticket = Ticket(
        ticket_id=uuid.uuid4(),
        client_company_id=client.client_id,
        title="Synthetic legacy ticket at the next current-series number",
        ticket_type="AR",
        current_priority=TicketPriority.MEDIUM,
        ticket_number=next_current_number,
        ticket_number_series=TICKET_NUMBER_SERIES_LEGACY,
    )
    db_session.add(legacy_ticket)
    await db_session.flush()

    _client_current, current_ticket = await _make_ticket(
        db_session, account_manager_id=account_manager.user_id
    )

    assert current_ticket.ticket_number == next_current_number
    assert current_ticket.ticket_number_series == TICKET_NUMBER_SERIES_CURRENT
    assert legacy_ticket.ticket_number == current_ticket.ticket_number
    assert legacy_ticket.ticket_number_series != current_ticket.ticket_number_series

    dupes = (
        await db_session.execute(
            text(
                "SELECT ticket_number, ticket_number_series, count(*) c FROM tickets "
                "WHERE ticket_number = :n "
                "GROUP BY ticket_number, ticket_number_series HAVING count(*) > 1"
            ),
            {"n": next_current_number},
        )
    ).all()
    assert dupes == []
