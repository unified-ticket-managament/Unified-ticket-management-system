# test_draft_retention_sweep.py
#
# Phase 2 hardening: the scheduled cleanup job for abandoned drafts and
# abandoned pasted inline images (app/core/draft_retention_scheduler.py,
# InteractionRepository.list_stale_drafts/list_stale_unclaimed_inline_
# images, InteractionService._discard_draft_core/_discard_stale_
# inline_image). Attachment cleanup is destructive, so this file
# explicitly proves the safe/unsafe boundary: a stale draft IS swept;
# every non-draft dispatch state (FAILED/PENDING_SEND/SENT/a retryable
# reply) is NEVER swept by the same query, regardless of age; a
# consumed inline image and an ordinary permanent attachment are never
# swept either.
#
# Runs against the real (dev) database inside a transaction rolled
# back at the end — same convention as test_send_idempotency.py /
# test_attachment_upload_authorization.py. The astext JSONB filter in
# list_stale_unclaimed_inline_images is Postgres-specific and can only
# be genuinely verified against a real Postgres session, not a mock.

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from shared_models.models import Role, User

from app.database.session import AsyncSessionLocal, engine
from app.ticketing.enums import InteractionDirection, InteractionStatus
from app.ticketing.models.attachment import Attachment
from app.ticketing.models.interaction import Interaction
from app.ticketing.repositories.attachment_repository import AttachmentRepository
from app.ticketing.repositories.interaction_repository import InteractionRepository
from app.ticketing.repositories.ticket_repository import TicketRepository
from app.ticketing.repositories.user_repository import UserRepository
from app.ticketing.schemas.attachment import AttachmentCreate
from app.ticketing.services.interaction_service import InteractionService

RETENTION_DAYS = 30


@pytest.fixture
async def db_session():
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.rollback()
    await engine.dispose()


class _FakeStorageService:
    """No real bucket access — records what would have been deleted."""

    def __init__(self):
        self.deleted_keys: list[str] = []

    async def delete(self, *, object_key: str) -> None:
        self.deleted_keys.append(object_key)


def _old_cutoff() -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=RETENTION_DAYS)


def _stale_created_at() -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=RETENTION_DAYS + 5)


def _fresh_created_at() -> datetime:
    return datetime.now(timezone.utc) - timedelta(hours=1)


async def _make_interaction(session, **overrides) -> Interaction:
    base = dict(
        interaction_id=uuid.uuid4(),
        interaction_type="EMAIL",
        status=InteractionStatus.PENDING,
        direction=InteractionDirection.OUTBOUND,
        payload={},
        is_visible=True,
        is_draft=False,
    )
    base.update(overrides)
    interaction = Interaction(**base)
    session.add(interaction)
    await session.flush()
    return interaction


async def _make_user(session) -> uuid.UUID:
    role = (await session.execute(select(Role).limit(1))).scalars().first()
    if role is None:
        pytest.skip("No seeded Role row available to attach a test User to.")

    user = User(
        user_id=uuid.uuid4(),
        name="Draft Retention Test User",
        email=f"draft-retention-{uuid.uuid4().hex[:8]}@example.com",
        password_hash="not-a-real-hash",
        role_id=role.role_id,
        is_active=True,
    )
    session.add(user)
    await session.flush()
    return user.user_id


def _service(db_session, storage_service) -> InteractionService:
    return InteractionService(
        interaction_repository=InteractionRepository(db_session),
        ticket_repository=TicketRepository(db_session),
        user_repository=UserRepository(db_session),
        attachment_repository=AttachmentRepository(db_session),
        storage_service=storage_service,
    )


# ---------------------------------------------------------
# list_stale_drafts — the safe/unsafe boundary
# ---------------------------------------------------------


async def test_list_stale_drafts_includes_old_draft(db_session):
    repo = InteractionRepository(db_session)
    stale_draft = await _make_interaction(
        db_session, is_draft=True, created_at=_stale_created_at()
    )

    results = await repo.list_stale_drafts(_old_cutoff())

    assert stale_draft.interaction_id in {i.interaction_id for i in results}


async def test_list_stale_drafts_excludes_fresh_draft(db_session):
    repo = InteractionRepository(db_session)
    fresh_draft = await _make_interaction(
        db_session, is_draft=True, created_at=_fresh_created_at()
    )

    results = await repo.list_stale_drafts(_old_cutoff())

    assert fresh_draft.interaction_id not in {i.interaction_id for i in results}


@pytest.mark.parametrize("dispatch_status", ["FAILED", "PENDING_SEND", "SENT"])
async def test_list_stale_drafts_never_includes_non_draft_dispatch_states(
    db_session, dispatch_status
):
    """
    The core destructive-cleanup safety guarantee: a real, old,
    non-draft interaction sitting in any dispatch state (FAILED —
    already failed and displayed to the agent; PENDING_SEND — still in
    its Undo-Send window; SENT — a real, delivered email) must NEVER
    be matched by this query, no matter how old it is — the query's
    only selector is is_draft=True, and none of these states are ever
    drafts.
    """

    repo = InteractionRepository(db_session)
    old_non_draft = await _make_interaction(
        db_session,
        is_draft=False,
        dispatch_status=dispatch_status,
        created_at=_stale_created_at(),
    )

    results = await repo.list_stale_drafts(_old_cutoff())

    assert old_non_draft.interaction_id not in {i.interaction_id for i in results}


async def test_list_stale_drafts_never_includes_retryable_reply(db_session):
    """A retryable failed reply is also is_draft=False — same
    guarantee as the parametrized dispatch-state test above, made
    explicit for the exact shape retry_failed_send operates on."""

    repo = InteractionRepository(db_session)
    old_retryable = await _make_interaction(
        db_session,
        interaction_type="REPLY",
        is_draft=False,
        dispatch_status="FAILED",
        payload={"dispatch_status": "FAILED", "dispatch_error": "boom"},
        created_at=_stale_created_at(),
    )

    results = await repo.list_stale_drafts(_old_cutoff())

    assert old_retryable.interaction_id not in {i.interaction_id for i in results}


# ---------------------------------------------------------
# list_stale_unclaimed_inline_images — the safe/unsafe boundary
# ---------------------------------------------------------


async def test_list_stale_unclaimed_inline_images_includes_old_unclaimed(db_session):
    repo = InteractionRepository(db_session)
    stale_inline = await _make_interaction(
        db_session,
        interaction_type="ATTACHMENT",
        payload={"file_count": 1, "is_inline": True},
        created_at=_stale_created_at(),
    )

    results = await repo.list_stale_unclaimed_inline_images(_old_cutoff())

    assert stale_inline.interaction_id in {i.interaction_id for i in results}


async def test_list_stale_unclaimed_inline_images_excludes_fresh_one(db_session):
    repo = InteractionRepository(db_session)
    fresh_inline = await _make_interaction(
        db_session,
        interaction_type="ATTACHMENT",
        payload={"file_count": 1, "is_inline": True},
        created_at=_fresh_created_at(),
    )

    results = await repo.list_stale_unclaimed_inline_images(_old_cutoff())

    assert fresh_inline.interaction_id not in {i.interaction_id for i in results}


async def test_list_stale_unclaimed_inline_images_excludes_already_consumed(db_session):
    """
    A consumed inline image (_reassign_inline_image_interactions
    already set is_visible=False once its attachment was reassigned
    onto a real sent interaction) must never be re-selected — proves
    no double-processing of an already-handled row.
    """

    repo = InteractionRepository(db_session)
    consumed = await _make_interaction(
        db_session,
        interaction_type="ATTACHMENT",
        payload={"file_count": 1, "is_inline": True},
        is_visible=False,
        created_at=_stale_created_at(),
    )

    results = await repo.list_stale_unclaimed_inline_images(_old_cutoff())

    assert consumed.interaction_id not in {i.interaction_id for i in results}


async def test_list_stale_unclaimed_inline_images_excludes_ordinary_attachment(db_session):
    """
    The core destructive-cleanup safety guarantee for this query: an
    ordinary, permanently-attached file (upload_attachment's own
    ATTACHMENT interaction — payload has no is_inline key at all) must
    NEVER be swept, no matter how old.
    """

    repo = InteractionRepository(db_session)
    ordinary_attachment = await _make_interaction(
        db_session,
        interaction_type="ATTACHMENT",
        payload={"file_count": 1},
        created_at=_stale_created_at(),
    )

    results = await repo.list_stale_unclaimed_inline_images(_old_cutoff())

    assert ordinary_attachment.interaction_id not in {i.interaction_id for i in results}


# ---------------------------------------------------------
# InteractionService._discard_draft_core / _discard_stale_inline_image
# ---------------------------------------------------------


async def test_discard_draft_core_deletes_attachments_and_draft_row(db_session):
    draft = await _make_interaction(db_session, is_draft=True, created_at=_stale_created_at())
    attachment_repo = AttachmentRepository(db_session)
    attachment = await attachment_repo.create(
        AttachmentCreate(
            interaction_id=draft.interaction_id,
            filename="pasted.png",
            storage_key="some/key.png",
        )
    )

    storage_service = _FakeStorageService()
    service = _service(db_session, storage_service)

    await service._discard_draft_core(draft)

    assert storage_service.deleted_keys == ["some/key.png"]
    remaining_attachment = (
        await db_session.execute(
            select(Attachment).where(Attachment.attachment_id == attachment.attachment_id)
        )
    ).scalar_one_or_none()
    assert remaining_attachment is None
    remaining_draft = (
        await db_session.execute(
            select(Interaction).where(Interaction.interaction_id == draft.interaction_id)
        )
    ).scalar_one_or_none()
    assert remaining_draft is None


async def test_discard_stale_inline_image_deletes_attachment_and_hides_not_deletes(db_session):
    """
    Unlike a draft (hard-deleted), an abandoned inline-image staging
    interaction is only hidden (is_visible=False) — same end-state a
    normally-consumed one already reaches, never a hard delete.
    """

    interaction = await _make_interaction(
        db_session,
        interaction_type="ATTACHMENT",
        payload={"file_count": 1, "is_inline": True},
        created_at=_stale_created_at(),
    )

    attachment_repo = AttachmentRepository(db_session)
    attachment = await attachment_repo.create(
        AttachmentCreate(
            interaction_id=interaction.interaction_id,
            filename="pasted.png",
            storage_key="another/key.png",
        )
    )

    storage_service = _FakeStorageService()
    service = _service(db_session, storage_service)

    await service._discard_stale_inline_image(interaction)

    assert storage_service.deleted_keys == ["another/key.png"]
    remaining_attachment = (
        await db_session.execute(
            select(Attachment).where(Attachment.attachment_id == attachment.attachment_id)
        )
    ).scalar_one_or_none()
    assert remaining_attachment is None

    reloaded_interaction = (
        await db_session.execute(
            select(Interaction).where(Interaction.interaction_id == interaction.interaction_id)
        )
    ).scalar_one()
    assert reloaded_interaction.is_visible is False


# ---------------------------------------------------------
# discard_draft (interactive endpoint) — regression lock for the
# pre-existing behavior this refactor must not have changed
# ---------------------------------------------------------


async def test_discard_draft_interactive_endpoint_still_works(db_session):
    user_id = await _make_user(db_session)
    root = await _make_interaction(db_session, is_draft=False, performed_by=None)
    draft = await _make_interaction(
        db_session,
        is_draft=True,
        performed_by=user_id,
        parent_interaction_id=root.interaction_id,
    )
    attachment_repo = AttachmentRepository(db_session)
    await attachment_repo.create(
        AttachmentCreate(
            interaction_id=draft.interaction_id,
            filename="draft-image.png",
            storage_key="draft/key.png",
        )
    )

    storage_service = _FakeStorageService()
    service = _service(db_session, storage_service)

    from unittest.mock import AsyncMock, patch

    current_user = AsyncMock()
    current_user.user_id = user_id

    with patch.object(
        service, "_resolve_pending_thread_root", AsyncMock(return_value=root)
    ), patch.object(
        service, "_ensure_can_act_on_pending_interaction", AsyncMock(return_value=None)
    ):
        response = await service.discard_draft(root.interaction_id, current_user)

    assert response.message == "Draft discarded."
    assert storage_service.deleted_keys == ["draft/key.png"]
    remaining_draft = (
        await db_session.execute(
            select(Interaction).where(Interaction.interaction_id == draft.interaction_id)
        )
    ).scalar_one_or_none()
    assert remaining_draft is None
