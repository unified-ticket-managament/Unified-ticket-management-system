# test_send_idempotency.py
#
# Coverage for P1 item 4 (send idempotency) in two layers:
#
# 1. DB-level: the real partial unique index on
#    (performed_by, dispatch_idempotency_key) — proves the actual
#    concurrency-safety mechanism a race between two requests relies
#    on. Runs against the real (dev) database inside a transaction
#    rolled back at the end (see test_interaction_threading.py's own
#    docstring for why); the one statement expected to violate the
#    constraint runs inside its own SAVEPOINT (begin_nested) so only
#    that attempt unwinds, leaving the rest of the test's own data
#    intact for the surrounding rollback to clean up — same idiom
#    interaction_service.py itself already uses elsewhere
#    (_attach_outbound_files' begin_nested), and it means this test
#    never needs a real commit (so nothing survives past this test).
# 2. Service-level: InteractionService.compose_email/retry_failed_send's
#    own idempotency-key branching, exercised against a fully mocked
#    InteractionRepository — proves the early-return-on-hit and the
#    IntegrityError-catch-and-recover paths are wired correctly,
#    without needing real cross-session concurrency (which Postgres's
#    own unique index already guarantees at the DB layer above).

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from shared_models.models import Role, User

from app.database.session import AsyncSessionLocal, engine
from app.ticketing.enums import InteractionDirection, InteractionStatus
from app.ticketing.models.interaction import Interaction
from app.ticketing.repositories.interaction_repository import InteractionRepository
from app.ticketing.schemas.compose import ComposeEmailRequest, ComposeEmailResponse
from app.ticketing.schemas.ticket_action import InteractionReplyResponse
from app.ticketing.services.interaction_service import InteractionService


@pytest.fixture
async def db_session():
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.rollback()
    await engine.dispose()


async def _make_user(session) -> uuid.UUID:
    role = (await session.execute(select(Role).limit(1))).scalars().first()
    if role is None:
        pytest.skip("No seeded Role row available to attach a test User to.")

    user = User(
        user_id=uuid.uuid4(),
        name="P1 Idempotency Test User",
        email=f"p1-idem-{uuid.uuid4().hex[:8]}@example.com",
        password_hash="not-a-real-hash",
        role_id=role.role_id,
        is_active=True,
    )
    session.add(user)
    await session.flush()
    return user.user_id


async def _make_reply_interaction(session, *, performed_by, idempotency_key) -> uuid.UUID:
    interaction_id = uuid.uuid4()
    session.add(
        Interaction(
            interaction_id=interaction_id,
            interaction_type="REPLY",
            status=InteractionStatus.ASSIGNED,
            direction=InteractionDirection.OUTBOUND,
            payload={"message": "test"},
            performed_by=performed_by,
            dispatch_idempotency_key=idempotency_key,
            is_visible=True,
        )
    )
    await session.flush()
    return interaction_id


# ---------------------------------------------------------
# 1. DB-level: the real unique constraint
# ---------------------------------------------------------


async def test_duplicate_key_for_the_same_user_violates_the_unique_index(db_session):
    repo = InteractionRepository(db_session)
    user_id = await _make_user(db_session)

    first_id = await _make_reply_interaction(
        db_session, performed_by=user_id, idempotency_key="dup-key-1"
    )

    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            await _make_reply_interaction(
                db_session, performed_by=user_id, idempotency_key="dup-key-1"
            )

    # The savepoint rollback undid only the second insert — the
    # first row (and this session's ability to keep querying) is
    # untouched, exactly like a losing concurrent request's own
    # rollback would leave the winner's already-committed row intact.
    found = await repo.get_by_idempotency_key("dup-key-1", user_id)
    assert found is not None
    assert found.interaction_id == first_id


async def test_same_key_for_different_users_does_not_conflict(db_session):
    user_a = await _make_user(db_session)
    user_b = await _make_user(db_session)

    id_a = await _make_reply_interaction(
        db_session, performed_by=user_a, idempotency_key="shared-key"
    )
    id_b = await _make_reply_interaction(
        db_session, performed_by=user_b, idempotency_key="shared-key"
    )

    assert id_a != id_b


async def test_multiple_null_keys_never_conflict(db_session):
    user_id = await _make_user(db_session)

    id_1 = await _make_reply_interaction(
        db_session, performed_by=user_id, idempotency_key=None
    )
    id_2 = await _make_reply_interaction(
        db_session, performed_by=user_id, idempotency_key=None
    )

    assert id_1 != id_2


# ---------------------------------------------------------
# 2. Service-level: compose_email's branching, fully mocked repository
# ---------------------------------------------------------


def _build_service(interaction_repository):
    return InteractionService(
        interaction_repository=interaction_repository,
        ticket_repository=AsyncMock(),
        user_repository=AsyncMock(),
        client_repository=AsyncMock(),
    )


async def test_compose_email_returns_existing_interaction_on_idempotency_hit():
    existing = Interaction(
        interaction_id=uuid.uuid4(),
        interaction_type="EMAIL",
        status=InteractionStatus.ASSIGNED,
        direction=InteractionDirection.OUTBOUND,
        payload={},
        client_id=uuid.uuid4(),
        created_at=datetime.now(timezone.utc),
    )

    repo = AsyncMock()
    repo.get_by_idempotency_key.return_value = existing

    service = _build_service(repo)
    current_user = AsyncMock()
    current_user.user_id = uuid.uuid4()

    request = ComposeEmailRequest(
        client_id=uuid.uuid4(),
        to_email="someone@painmedpa.com",
        subject="Test",
        message="Hello",
        idempotency_key="the-key",
    )

    response = await service.compose_email(request=request, current_user=current_user)

    assert isinstance(response, ComposeEmailResponse)
    assert response.interaction_id == existing.interaction_id
    assert response.client_id == existing.client_id
    # The fast path must skip all downstream work entirely — no
    # client lookup, no envelope build, no second interaction created.
    service.client_repository.get_by_id.assert_not_called()
    repo.create.assert_not_called()


async def test_compose_email_recovers_from_concurrent_integrity_error():
    existing = Interaction(
        interaction_id=uuid.uuid4(),
        interaction_type="EMAIL",
        status=InteractionStatus.ASSIGNED,
        direction=InteractionDirection.OUTBOUND,
        payload={},
        client_id=uuid.uuid4(),
        created_at=datetime.now(timezone.utc),
    )

    repo = AsyncMock()
    # First lookup (the fast path) finds nothing — this request "wins
    # the race" up to the create() call; the second lookup (after the
    # IntegrityError) finds what the concurrent request actually
    # inserted first.
    repo.get_by_idempotency_key.side_effect = [None, existing]
    repo.create.side_effect = IntegrityError("duplicate key", {}, BaseException())

    service = _build_service(repo)

    fake_client = AsyncMock()
    fake_client.client_id = uuid.uuid4()
    fake_client.is_active = True
    fake_client.inbox_email = "shared@example.com"
    fake_client.account_manager_id = uuid.uuid4()
    fake_client.name = "Test Client"
    service.client_repository.get_by_id.return_value = fake_client
    # Keeps _resolve_account_manager_email's own Cc-lookup a clean
    # no-op (None) rather than an unconstrained Mock flowing into the
    # envelope's account_manager_email: str | None field.
    service.user_repository.get_by_id.return_value = None

    current_user = SimpleNamespace(
        user_id=uuid.uuid4(),
        name="Agent",
        role=SimpleNamespace(name="Staff"),
        permissions=["communication:create"],
        designation=None,
        department=None,
        phone_number=None,
    )

    request = ComposeEmailRequest(
        client_id=fake_client.client_id,
        to_email="someone@painmedpa.com",
        subject="Test",
        message="Hello",
        idempotency_key="racing-key",
    )

    response = await service.compose_email(request=request, current_user=current_user)

    assert response.interaction_id == existing.interaction_id
    repo.db.rollback.assert_awaited()


# ---------------------------------------------------------
# 3. Phase 2 hardening: send_draft idempotency — the one send path
# that previously had none at all. Service-level, mocked repository —
# same style as compose_email's own coverage above.
# ---------------------------------------------------------


def _global_inbox_user() -> SimpleNamespace:
    return SimpleNamespace(
        user_id=uuid.uuid4(),
        name="Super Admin User",
        role=SimpleNamespace(name="Super Admin"),
        permissions=[],
        designation=None,
        department=None,
        phone_number=None,
    )


def _root_interaction() -> Interaction:
    return Interaction(
        interaction_id=uuid.uuid4(),
        interaction_type="EMAIL",
        status=InteractionStatus.PENDING,
        direction=InteractionDirection.INBOUND,
        payload={},
        client_id=None,
        category_id=None,
        ticket_id=None,
        created_at=datetime.now(timezone.utc),
    )


async def test_send_draft_idempotency_hit_short_circuits_before_get_draft():
    """
    The core regression guard for the ordering subtlety: a retry with
    an idempotency key that already matches a completed send must
    return that existing result WITHOUT ever calling get_draft — a
    successful prior send already hard-deletes the draft row, so
    reaching get_draft here (as a naive copy of the other four send
    paths' template would) would incorrectly 404 instead of returning
    the original result.
    """

    root = _root_interaction()
    existing = Interaction(
        interaction_id=uuid.uuid4(),
        interaction_type="REPLY",
        status=InteractionStatus.ASSIGNED,
        direction=InteractionDirection.OUTBOUND,
        payload={"message": "already sent"},
        created_at=datetime.now(timezone.utc),
    )

    repo = AsyncMock()
    repo.get_by_id.return_value = root
    repo.find_thread_root.return_value = root
    repo.get_by_idempotency_key.return_value = existing

    service = _build_service(repo)
    current_user = _global_inbox_user()

    response = await service.send_draft(
        interaction_id=root.interaction_id,
        current_user=current_user,
        idempotency_key="already-sent-key",
    )

    assert isinstance(response, InteractionReplyResponse)
    assert response.interaction_id == existing.interaction_id
    assert response.parent_interaction_id == root.interaction_id
    # The regression this test exists for: get_draft must never be
    # reached on an idempotency hit.
    repo.get_draft.assert_not_called()


async def test_send_draft_without_idempotency_key_still_404s_with_no_draft():
    """
    Regression guard for the default (no idempotency_key) case: byte-
    for-byte the same pre-existing behavior — no draft on the thread
    still raises 404, unaffected by the new pre-check being present.
    """

    root = _root_interaction()

    repo = AsyncMock()
    repo.get_by_id.return_value = root
    repo.find_thread_root.return_value = root
    repo.get_draft.return_value = None

    service = _build_service(repo)
    current_user = _global_inbox_user()

    with pytest.raises(HTTPException) as exc_info:
        await service.send_draft(interaction_id=root.interaction_id, current_user=current_user)

    assert exc_info.value.status_code == 404
    repo.get_by_idempotency_key.assert_not_called()


async def test_send_draft_threads_idempotency_key_into_add_interaction_reply():
    """
    A real (non-hit) send must pass the caller's idempotency_key
    through to add_interaction_reply (which owns the actual insert/
    IntegrityError-recovery race — see that method's own coverage) —
    proven here by spying on the request object add_interaction_reply
    actually receives, rather than re-exercising the full envelope/
    dispatch path a second time.
    """

    root = _root_interaction()
    draft_interaction_id = uuid.uuid4()
    draft = Interaction(
        interaction_id=draft_interaction_id,
        interaction_type="REPLY",
        status=InteractionStatus.ASSIGNED,
        direction=InteractionDirection.OUTBOUND,
        payload={"message": "draft body", "cc": [], "bcc": []},
        is_draft=True,
        created_at=datetime.now(timezone.utc),
    )

    repo = AsyncMock()
    repo.get_by_id.return_value = root
    repo.find_thread_root.return_value = root
    repo.get_by_idempotency_key.return_value = None
    repo.get_draft.return_value = draft

    service = _build_service(repo)
    service.attachment_repository = AsyncMock()

    captured_requests = []

    async def _fake_add_interaction_reply(
        interaction_id, request, current_user, existing_attachment_source_interaction_id=None
    ):
        captured_requests.append(request)
        return InteractionReplyResponse(
            interaction_id=uuid.uuid4(),
            parent_interaction_id=root.interaction_id,
            message=request.message,
            created_at=datetime.now(timezone.utc),
        )

    service.add_interaction_reply = _fake_add_interaction_reply

    current_user = _global_inbox_user()

    await service.send_draft(
        interaction_id=root.interaction_id,
        current_user=current_user,
        idempotency_key="fresh-key",
    )

    assert len(captured_requests) == 1
    assert captured_requests[0].idempotency_key == "fresh-key"
    repo.delete_draft.assert_awaited_once()
    service.attachment_repository.reassign_interaction.assert_awaited_once()
