# test_sent_replied_dispatch_status.py
#
# Regression coverage for Issue 1 (Send/Undo/Sent inconsistency):
# InteractionRepository.list_sent/list_replied used to filter only on
# interaction_type/direction/performed_by/is_visible(/is_draft) — never
# on dispatch_status. Since an outbound interaction is created
# dispatch_status="PENDING_SEND" *before* Graph is ever called (so
# Undo Send has something to cancel), a still-pending, Graph-rejected
# (FAILED), or user-canceled (CANCELED) message rendered identically
# to a real SENT one in the Mail UI's Sent/Replied folders. Both list
# methods now require dispatch_status == "SENT".
#
# Runs against the real (dev) database inside a transaction that is
# always rolled back at the end — same convention as
# test_undo_send.py/test_ticket_status_on_assignment.py.

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.orm import joinedload
from shared_models.models import Role, User

from app.database.session import AsyncSessionLocal, engine
from app.ticketing.enums import InteractionDirection
from app.ticketing.repositories.interaction_repository import InteractionRepository
from app.ticketing.schemas.interaction import InteractionCreate


@pytest.fixture
async def db_session():
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.rollback()
    await engine.dispose()


async def _get_user_by_role(session, role_name: str) -> User:
    result = await session.execute(
        select(User)
        .options(joinedload(User.role))
        .join(Role, Role.role_id == User.role_id)
        .where(Role.name == role_name, User.is_active.is_(True))
    )
    users = result.unique().scalars().all()
    if users:
        return users[0]
    pytest.skip(f"No active seeded {role_name!r} found.")


async def _make_sent_root(session, *, performed_by, dispatch_status: str, is_draft: bool = False):
    """A Compose-shaped thread root: interaction_type=EMAIL, no parent — the shape list_sent selects on."""

    repository = InteractionRepository(session)
    return await repository.create(
        InteractionCreate(
            ticket_id=None,
            interaction_type="EMAIL",
            direction=InteractionDirection.OUTBOUND,
            performed_by=performed_by,
            payload={"message": "dispatch-status test", "dispatch_status": dispatch_status},
            is_visible=True,
            is_draft=is_draft,
            parent_interaction_id=None,
            dispatch_status=dispatch_status,
        )
    )


async def _make_reply(session, *, performed_by, dispatch_status: str, is_draft: bool = False):
    """A Reply-shaped interaction — the shape list_replied selects on."""

    repository = InteractionRepository(session)
    return await repository.create(
        InteractionCreate(
            ticket_id=None,
            interaction_type="REPLY",
            direction=InteractionDirection.OUTBOUND,
            performed_by=performed_by,
            payload={"message": "dispatch-status test", "dispatch_status": dispatch_status},
            is_visible=True,
            is_draft=is_draft,
            dispatch_status=dispatch_status,
        )
    )


ALL_STATUSES = ["PENDING_SEND", "SENT", "FAILED", "CANCELED"]


async def test_list_sent_only_returns_sent_rows(db_session):
    sender = await _get_user_by_role(db_session, "Staff")

    created = {
        status: await _make_sent_root(db_session, performed_by=sender.user_id, dispatch_status=status)
        for status in ALL_STATUSES
    }

    repository = InteractionRepository(db_session)
    results = await repository.list_sent(sender.user_id)
    result_ids = {r.interaction_id for r in results}

    assert created["SENT"].interaction_id in result_ids
    assert created["PENDING_SEND"].interaction_id not in result_ids
    assert created["FAILED"].interaction_id not in result_ids
    assert created["CANCELED"].interaction_id not in result_ids


async def test_list_replied_only_returns_sent_rows(db_session):
    sender = await _get_user_by_role(db_session, "Staff")

    created = {
        status: await _make_reply(db_session, performed_by=sender.user_id, dispatch_status=status)
        for status in ALL_STATUSES
    }

    repository = InteractionRepository(db_session)
    results = await repository.list_replied(sender.user_id)
    result_ids = {r.interaction_id for r in results}

    assert created["SENT"].interaction_id in result_ids
    assert created["PENDING_SEND"].interaction_id not in result_ids
    assert created["FAILED"].interaction_id not in result_ids
    assert created["CANCELED"].interaction_id not in result_ids


async def test_list_replied_still_excludes_drafts_regardless_of_dispatch_status(db_session):
    """
    Pre-existing is_draft.is_(False) guard must keep working alongside
    the new dispatch_status filter — a draft is never "sent" even if
    some stale/inconsistent row happened to carry dispatch_status="SENT".
    """

    sender = await _get_user_by_role(db_session, "Staff")
    draft = await _make_reply(
        db_session, performed_by=sender.user_id, dispatch_status="SENT", is_draft=True
    )

    repository = InteractionRepository(db_session)
    results = await repository.list_replied(sender.user_id)
    result_ids = {r.interaction_id for r in results}

    assert draft.interaction_id not in result_ids


async def test_list_sent_and_list_replied_scoped_to_performed_by(db_session):
    sender = await _get_user_by_role(db_session, "Staff")
    other = await _get_user_by_role(db_session, "Team Lead")

    mine = await _make_sent_root(db_session, performed_by=sender.user_id, dispatch_status="SENT")
    theirs = await _make_sent_root(db_session, performed_by=other.user_id, dispatch_status="SENT")

    repository = InteractionRepository(db_session)
    results = await repository.list_sent(sender.user_id)
    result_ids = {r.interaction_id for r in results}

    assert mine.interaction_id in result_ids
    assert theirs.interaction_id not in result_ids
