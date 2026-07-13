# test_interaction_threading.py
#
# Regression coverage for the Interactions/Mail thread-reconstruction
# fix: InteractionRepository.find_thread_root and .list_thread are now
# recursive-CTE-based (correct at any nesting depth) rather than a
# single parent_interaction_id hop, which silently returned the wrong
# "root" and dropped nested descendants past the first level.
#
# Runs against the real (dev) database inside a transaction that is
# always rolled back at the end — no synthetic data from this file is
# ever persisted. There is no separate test database configured for
# this project (see the two existing test files: one has no DB
# dependency at all, the other exercises a dependency function
# directly) — this is the rollback-transaction approach the project's
# own validation checklist calls for in that situation.

import uuid

import pytest
from sqlalchemy import update

from app.database.session import AsyncSessionLocal, engine
from app.ticketing.enums import InteractionDirection, InteractionStatus
from app.ticketing.models.interaction import Interaction
from app.ticketing.repositories.interaction_repository import InteractionRepository


@pytest.fixture
async def db_session():
    # pytest-asyncio gives each test function its own event loop, but
    # `engine`'s connection pool is a module-level singleton created
    # once at import time — a connection opened under one test's loop
    # gets pooled and then handed to the next test's *different* loop,
    # which asyncpg rejects ("Event loop is closed"). Disposing the
    # pool after every test forces the next one to open a fresh
    # connection bound to its own current loop.
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.rollback()
    await engine.dispose()


async def _make_interaction(session, *, parent_id=None, interaction_type="REPLY"):
    interaction_id = uuid.uuid4()
    session.add(
        Interaction(
            interaction_id=interaction_id,
            interaction_type=interaction_type,
            status=InteractionStatus.PENDING,
            direction=(
                InteractionDirection.INBOUND
                if interaction_type == "EMAIL"
                else InteractionDirection.OUTBOUND
            ),
            payload={"message": "test"},
            parent_interaction_id=parent_id,
            is_visible=True,
        )
    )
    await session.flush()
    return interaction_id


async def test_find_thread_root_resolves_flat_reply_to_its_root(db_session):
    """The common case in this app's real data: every reply's
    parent_interaction_id already points directly at the root."""

    repo = InteractionRepository(db_session)
    root_id = await _make_interaction(db_session, interaction_type="EMAIL")
    reply_id = await _make_interaction(db_session, parent_id=root_id)

    resolved = await repo.find_thread_root(reply_id)

    assert resolved is not None
    assert resolved.interaction_id == root_id


async def test_find_thread_root_resolves_deeply_nested_descendant(db_session):
    """
    A -> B -> C -> E, and A -> B -> D (the exact shape from the bug
    report). Clicking any of A/B/C/D/E must resolve to A — a single
    parent_interaction_id hop would incorrectly return B (for C/D) or
    C (for E) instead of the true root.
    """

    repo = InteractionRepository(db_session)
    a = await _make_interaction(db_session, interaction_type="EMAIL")
    b = await _make_interaction(db_session, parent_id=a)
    c = await _make_interaction(db_session, parent_id=b)
    d = await _make_interaction(db_session, parent_id=b)
    e = await _make_interaction(db_session, parent_id=c)

    for node in (a, b, c, d, e):
        resolved = await repo.find_thread_root(node)
        assert resolved is not None
        assert resolved.interaction_id == a, f"expected root a for node {node}, got {resolved.interaction_id}"


async def test_list_thread_returns_every_descendant_at_any_depth(db_session):
    """
    Same shape as above — list_thread(a) must return {b, c, d, e},
    not just the direct children {b}. This is the actual "open an
    interaction and see the full conversation" behavior.
    """

    repo = InteractionRepository(db_session)
    a = await _make_interaction(db_session, interaction_type="EMAIL")
    b = await _make_interaction(db_session, parent_id=a)
    c = await _make_interaction(db_session, parent_id=b)
    d = await _make_interaction(db_session, parent_id=b)
    e = await _make_interaction(db_session, parent_id=c)

    thread = await repo.list_thread(a)
    thread_ids = {item.interaction_id for item in thread}

    assert thread_ids == {b, c, d, e}


async def test_list_thread_excludes_unrelated_interactions(db_session):
    """A second, unrelated root's replies must never appear when
    fetching the first root's thread."""

    repo = InteractionRepository(db_session)
    root_a = await _make_interaction(db_session, interaction_type="EMAIL")
    reply_a = await _make_interaction(db_session, parent_id=root_a)

    root_x = await _make_interaction(db_session, interaction_type="EMAIL")
    reply_x = await _make_interaction(db_session, parent_id=root_x)

    thread = await repo.list_thread(root_a)
    thread_ids = {item.interaction_id for item in thread}

    assert thread_ids == {reply_a}
    assert reply_x not in thread_ids
    assert root_x not in thread_ids


async def test_list_thread_excludes_hidden_replies(db_session):
    """A soft-deleted (is_visible=False) reply must not appear in the
    reconstructed thread — same visibility rule as before this fix."""

    repo = InteractionRepository(db_session)
    root_id = await _make_interaction(db_session, interaction_type="EMAIL")
    visible_reply = await _make_interaction(db_session, parent_id=root_id)
    hidden_reply_id = await _make_interaction(db_session, parent_id=root_id)

    await db_session.execute(
        update(Interaction)
        .where(Interaction.interaction_id == hidden_reply_id)
        .values(is_visible=False)
    )
    await db_session.flush()

    thread = await repo.list_thread(root_id)
    thread_ids = {item.interaction_id for item in thread}

    assert visible_reply in thread_ids
    assert hidden_reply_id not in thread_ids


async def test_find_thread_root_returns_none_for_nonexistent_id(db_session):
    repo = InteractionRepository(db_session)

    resolved = await repo.find_thread_root(uuid.uuid4())

    assert resolved is None
