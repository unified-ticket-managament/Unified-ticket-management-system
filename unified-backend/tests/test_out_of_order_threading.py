# test_out_of_order_threading.py
#
# Regression coverage for P1 item 3 (out-of-order email delivery) and
# the inbound provider_message_id column fix from item 2. Runs against
# the real (dev) database inside a transaction that is always rolled
# back at the end — same convention as test_interaction_threading.py
# (see that file's own docstring for why: no separate test database
# exists for this project). Per this repo's known pytest-asyncio
# event-loop-scope fragility, run this file alone, not in the same
# pytest process as another DB-touching test file.

import uuid

import pytest
from sqlalchemy import select
from shared_models.models import Role, User

from app.database.session import AsyncSessionLocal, engine
from app.ticketing.enums import InteractionDirection, InteractionStatus
from app.ticketing.models.interaction import Interaction
from app.ticketing.repositories.interaction_repository import InteractionRepository
from app.ticketing.services.email_service import EmailService


async def _make_user(session) -> uuid.UUID:
    """
    A throwaway User row for interactions.performed_by/claimed_by's
    real FK constraint — flushed only, rolled back with everything
    else db_session creates. Reuses whatever Role is already seeded
    (see test_category_transfer.py's identical convention) rather
    than assuming a specific role name exists.
    """

    role = (await session.execute(select(Role).limit(1))).scalars().first()
    if role is None:
        pytest.skip("No seeded Role row available to attach a test User to.")

    user = User(
        user_id=uuid.uuid4(),
        name="P1 Test User",
        email=f"p1-test-{uuid.uuid4().hex[:8]}@example.com",
        password_hash="not-a-real-hash",
        role_id=role.role_id,
        is_active=True,
    )
    session.add(user)
    await session.flush()
    return user.user_id


@pytest.fixture
async def db_session():
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.rollback()
    await engine.dispose()


async def _make_interaction(
    session,
    *,
    message_id=None,
    in_reply_to_message_id=None,
    references=None,
    parent_id=None,
    ticket_id=None,
    claimed_by=None,
    status=InteractionStatus.PENDING,
    interaction_type="EMAIL",
    performed_by=None,
    dispatch_idempotency_key=None,
    dispatch_status=None,
):
    interaction_id = uuid.uuid4()
    session.add(
        Interaction(
            interaction_id=interaction_id,
            interaction_type=interaction_type,
            status=status,
            direction=(
                InteractionDirection.INBOUND
                if interaction_type == "EMAIL"
                else InteractionDirection.OUTBOUND
            ),
            payload={"message": "test"},
            message_id=message_id,
            in_reply_to_message_id=in_reply_to_message_id,
            references=references,
            parent_interaction_id=parent_id,
            ticket_id=ticket_id,
            claimed_by=claimed_by,
            performed_by=performed_by,
            dispatch_idempotency_key=dispatch_idempotency_key,
            dispatch_status=dispatch_status,
            is_visible=True,
        )
    )
    await session.flush()
    return interaction_id


# ---------------------------------------------------------
# find_orphans_awaiting_parent / reparent — the reconciliation core
# ---------------------------------------------------------


async def test_reply_before_original_is_reconciled_once_original_arrives(db_session):
    repo = InteractionRepository(db_session)

    # The reply arrives first — nothing to thread-match against yet,
    # so it lands as its own (accidental) root, in_reply_to pointing
    # at a message_id that doesn't exist in the table yet.
    orphan_id = await _make_interaction(
        db_session, message_id="<reply@example.com>", in_reply_to_message_id="<original@example.com>"
    )

    orphans = await repo.find_orphans_awaiting_parent("<original@example.com>")
    assert [o.interaction_id for o in orphans] == [orphan_id]

    # The original itself now arrives.
    original_id = await _make_interaction(db_session, message_id="<original@example.com>")

    for orphan in orphans:
        await repo.reparent(orphan, original_id)

    reparented = await repo.get_by_id(orphan_id)
    assert reparented.parent_interaction_id == original_id

    # Once reparented, it's no longer an orphan awaiting this parent.
    assert await repo.find_orphans_awaiting_parent("<original@example.com>") == []


async def test_reply_matched_via_references_is_reconciled(db_session):
    repo = InteractionRepository(db_session)

    orphan_id = await _make_interaction(
        db_session,
        message_id="<reply2@example.com>",
        in_reply_to_message_id="<some-other-msg@example.com>",
        references=["<unrelated@example.com>", "<original2@example.com>"],
    )

    orphans = await repo.find_orphans_awaiting_parent("<original2@example.com>")
    assert [o.interaction_id for o in orphans] == [orphan_id]


async def test_original_before_reply_needs_no_reconciliation(db_session):
    """Regression: the normal (already-correct) ordering must stay
    exactly as it works today — receive_email's own forward-direction
    check (get_by_message_ids) links the reply the moment it arrives,
    so find_orphans_awaiting_parent should simply find nothing to do
    (the reply was never left parentless in the first place)."""

    repo = InteractionRepository(db_session)

    original_id = await _make_interaction(db_session, message_id="<original3@example.com>")
    # Simulates the reply having already been linked at creation time
    # (parent_interaction_id set, exactly as email_service.py's normal
    # forward-direction match would do) — never a parentless orphan.
    await _make_interaction(
        db_session,
        message_id="<reply3@example.com>",
        in_reply_to_message_id="<original3@example.com>",
        parent_id=original_id,
    )

    orphans = await repo.find_orphans_awaiting_parent("<original3@example.com>")
    assert orphans == []


async def test_orphan_already_claimed_is_not_reconciled(db_session):
    """An orphan an agent has already acted on (claimed) is left
    alone — reconciliation only ever touches an untouched, still-
    PENDING, unclaimed, unticketed row. This is what keeps the fix
    purely structural and never retroactively disturbs SLA/ticket
    state an agent's already-taken action depends on."""

    repo = InteractionRepository(db_session)
    some_agent_id = await _make_user(db_session)

    await _make_interaction(
        db_session,
        message_id="<reply4@example.com>",
        in_reply_to_message_id="<original4@example.com>",
        claimed_by=some_agent_id,
    )

    orphans = await repo.find_orphans_awaiting_parent("<original4@example.com>")
    assert orphans == []


async def test_unrelated_emails_are_never_merged(db_session):
    """Two emails that merely happen to exist around the same time,
    with no message_id/in_reply_to/references relationship, must
    never be reconciled — matching is exact-string-equality only."""

    repo = InteractionRepository(db_session)

    await _make_interaction(
        db_session,
        message_id="<unrelated-a@example.com>",
        in_reply_to_message_id="<something-else-entirely@example.com>",
    )

    orphans = await repo.find_orphans_awaiting_parent("<totally-unrelated@example.com>")
    assert orphans == []


async def test_reconcile_orphaned_replies_end_to_end_via_email_service(db_session):
    """Exercises EmailService._reconcile_orphaned_replies directly —
    the actual call site wired into receive_email right after the
    original interaction is persisted."""

    repo = InteractionRepository(db_session)
    service = EmailService(
        interaction_repository=repo,
        client_repository=None,
        attachment_service=None,
    )

    orphan_id = await _make_interaction(
        db_session,
        message_id="<reply5@example.com>",
        in_reply_to_message_id="<original5@example.com>",
    )
    original_id = await _make_interaction(db_session, message_id="<original5@example.com>")
    original = await repo.get_by_id(original_id)

    await service._reconcile_orphaned_replies(original, "<original5@example.com>")

    reparented = await repo.get_by_id(orphan_id)
    assert reparented.parent_interaction_id == original_id


# ---------------------------------------------------------
# get_by_idempotency_key — item 4's lookup
# ---------------------------------------------------------


async def test_get_by_idempotency_key_scopes_to_the_same_user(db_session):
    repo = InteractionRepository(db_session)
    user_a = await _make_user(db_session)
    user_b = await _make_user(db_session)

    interaction_id = await _make_interaction(
        db_session,
        interaction_type="REPLY",
        performed_by=user_a,
        dispatch_idempotency_key="key-123",
    )

    found = await repo.get_by_idempotency_key("key-123", user_a)
    assert found is not None
    assert found.interaction_id == interaction_id

    not_found = await repo.get_by_idempotency_key("key-123", user_b)
    assert not_found is None


# ---------------------------------------------------------
# try_transition_to_pending_send — item 5's CAS guard
# ---------------------------------------------------------


async def test_try_transition_to_pending_send_succeeds_only_from_failed(db_session):
    repo = InteractionRepository(db_session)

    failed_id = await _make_interaction(
        db_session, interaction_type="REPLY", dispatch_status="FAILED"
    )

    result = await repo.try_transition_to_pending_send(failed_id)
    assert result is not None
    assert result.dispatch_status == "PENDING_SEND"

    # A second attempt (simulating a concurrent double-click, or a
    # retry after it's already been moved off FAILED) must not win
    # again — this is the actual duplicate-send guard.
    second_result = await repo.try_transition_to_pending_send(failed_id)
    assert second_result is None


async def test_try_transition_to_pending_send_rejects_non_failed_statuses(db_session):
    repo = InteractionRepository(db_session)

    for status in ("SENT", "PENDING_SEND", "CANCELED", None):
        interaction_id = await _make_interaction(
            db_session, interaction_type="REPLY", dispatch_status=status
        )
        result = await repo.try_transition_to_pending_send(interaction_id)
        assert result is None, f"expected no transition from dispatch_status={status!r}"
