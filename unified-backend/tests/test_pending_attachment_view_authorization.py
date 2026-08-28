# test_pending_attachment_view_authorization.py
#
# Phase 6 / BD-HC6 approved fix: AttachmentService._resolve_and_authorize's
# pre-ticket branch (a not-yet-ticketed interaction's attachment — e.g.
# a file on a pending mailbox item) previously bypassed via
# SUPERVISOR_ROLE_NAMES ({Team Lead, Account Manager, Site Lead, Super
# Admin}), wider than every sibling pending-item gate in
# access_control.py (claim/archive/snooze/tag/folder/forward/reply,
# and the pending-interaction view gate itself), all of which use the
# narrower GLOBAL_INBOX_ROLE_NAMES ({Site Lead, Super Admin}). Narrowed
# to GLOBAL_INBOX_ROLE_NAMES to match — Team Lead/Account Manager no
# longer get an unconditional bypass on a path they can't otherwise
# see or act on via any other pending-item route. The agent-name
# fallback for a role outside that set (comparing
# interaction.payload["agent_name"] to current_user.name) is
# unaffected by this change.
#
# Same convention as test_attachment_upload_authorization.py: real
# DB-backed AttachmentService against a throwaway Interaction/
# Attachment pair (ticket_id=None, so the pre-ticket branch under test
# is actually reached), everything inside a transaction that is always
# rolled back. Run this file individually (DB-touching test caveat).

import uuid
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import joinedload
from shared_models.models import Role, User

from app.database.session import AsyncSessionLocal, engine
from app.ticketing.enums import InteractionDirection, InteractionStatus
from app.ticketing.models.attachment import Attachment
from app.ticketing.models.interaction import Interaction
from app.ticketing.repositories.attachment_repository import AttachmentRepository
from app.ticketing.repositories.client_repository import ClientRepository
from app.ticketing.repositories.interaction_repository import InteractionRepository
from app.ticketing.repositories.ticket_repository import TicketRepository
from app.ticketing.services.attachment_service import AttachmentService
from app.ticketing.storage.base import StorageService


class _FakeStorageService(StorageService):
    """Read-only stand-in — these tests never upload, only resolve/
    view an already-existing attachment row."""

    bucket = "test-bucket"

    async def upload(self, *, data: bytes, object_key: str, content_type: str) -> None:
        raise NotImplementedError

    async def download(self, *, object_key: str) -> bytes:
        return b"fake-bytes"

    async def delete(self, *, object_key: str) -> None:
        raise NotImplementedError

    async def exists(self, *, object_key: str) -> bool:
        return True

    async def presigned_get_url(
        self, *, object_key: str, filename: str, inline: bool = False
    ) -> str:
        return f"https://fake-storage.test/{object_key}"


@pytest.fixture
async def db_session():
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.rollback()
    await engine.dispose()


def _build_service(session) -> AttachmentService:
    return AttachmentService(
        attachment_repository=AttachmentRepository(session),
        interaction_repository=InteractionRepository(session),
        ticket_repository=TicketRepository(session),
        storage_service=_FakeStorageService(),
        client_repository=ClientRepository(session),
    )


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


async def _make_pending_attachment(session, *, assigned_agent_name: str | None) -> Attachment:
    """A not-yet-ticketed interaction (ticket_id=None) with one
    attachment — the exact shape _resolve_and_authorize's pre-ticket
    branch handles. assigned_agent_name mirrors the inbox's own
    payload["agent_name"] scoping the agent-name fallback checks."""

    interaction = Interaction(
        interaction_id=uuid.uuid4(),
        ticket_id=None,
        interaction_type="EMAIL",
        status=InteractionStatus.PENDING,
        direction=InteractionDirection.INBOUND,
        payload={"agent_name": assigned_agent_name} if assigned_agent_name else {},
        created_at=datetime.now(timezone.utc),
    )
    session.add(interaction)
    await session.flush()

    attachment = Attachment(
        attachment_id=uuid.uuid4(),
        interaction_id=interaction.interaction_id,
        filename="pending-item.pdf",
        mime_type="application/pdf",
        size_bytes=1024,
        storage_key=f"test/{uuid.uuid4().hex}.pdf",
        bucket_name="test-bucket",
        uploaded_at=datetime.now(timezone.utc),
    )
    session.add(attachment)
    await session.flush()
    return attachment


# ---------------------------------------------------------
# Positive: Super Admin / Site Lead — GLOBAL_INBOX_ROLE_NAMES bypass,
# unconditional, unaffected by this fix.
# ---------------------------------------------------------


@pytest.mark.parametrize("role_name", ["Super Admin", "Site Lead"])
async def test_global_inbox_roles_can_view_pending_attachment(db_session, role_name):
    actor = await _get_user_by_role(db_session, role_name)
    attachment = await _make_pending_attachment(
        db_session, assigned_agent_name="Someone Else Entirely"
    )

    service = _build_service(db_session)
    result = await service.get_attachment(attachment.attachment_id, current_user=actor)
    assert result.filename == "pending-item.pdf"


# ---------------------------------------------------------
# Negative: Team Lead / Account Manager — this is the actual behavior
# change under test. Previously bypassed unconditionally via
# SUPERVISOR_ROLE_NAMES; now denied unless they happen to match the
# agent-name fallback (they don't, here), same as any other
# non-global-inbox role.
# ---------------------------------------------------------


@pytest.mark.parametrize("role_name", ["Team Lead", "Account Manager"])
async def test_team_lead_and_account_manager_now_denied(db_session, role_name):
    actor = await _get_user_by_role(db_session, role_name)
    attachment = await _make_pending_attachment(
        db_session, assigned_agent_name="Someone Else Entirely"
    )

    service = _build_service(db_session)
    with pytest.raises(HTTPException) as exc_info:
        await service.get_attachment(attachment.attachment_id, current_user=actor)
    assert exc_info.value.status_code == 403


# ---------------------------------------------------------
# Negative: Staff — unaffected either way, was never in
# SUPERVISOR_ROLE_NAMES or GLOBAL_INBOX_ROLE_NAMES, still denied unless
# the agent-name fallback matches.
# ---------------------------------------------------------


async def test_staff_denied_when_not_the_assigned_agent(db_session):
    actor = await _get_user_by_role(db_session, "Staff")
    attachment = await _make_pending_attachment(
        db_session, assigned_agent_name="Someone Else Entirely"
    )

    service = _build_service(db_session)
    with pytest.raises(HTTPException) as exc_info:
        await service.get_attachment(attachment.attachment_id, current_user=actor)
    assert exc_info.value.status_code == 403


# ---------------------------------------------------------
# Regression: the agent-name fallback itself is unaffected by this
# fix — a non-global-inbox role whose name matches payload["agent_name"]
# still succeeds, exactly as before.
# ---------------------------------------------------------


async def test_agent_name_fallback_still_works_for_matching_staff(db_session):
    actor = await _get_user_by_role(db_session, "Staff")
    attachment = await _make_pending_attachment(db_session, assigned_agent_name=actor.name)

    service = _build_service(db_session)
    result = await service.get_attachment(attachment.attachment_id, current_user=actor)
    assert result.filename == "pending-item.pdf"


async def test_no_payload_agent_name_falls_through_for_non_global_inbox_role(db_session):
    """payload.get("agent_name") is None -> the fallback's own
    `if payload_agent is not None` guard means no rejection fires,
    same pre-existing behavior as before this fix."""

    actor = await _get_user_by_role(db_session, "Team Lead")
    attachment = await _make_pending_attachment(db_session, assigned_agent_name=None)

    service = _build_service(db_session)
    result = await service.get_attachment(attachment.attachment_id, current_user=actor)
    assert result.filename == "pending-item.pdf"


# ---------------------------------------------------------
# Regression: the ticketed-attachment branch (interaction.ticket_id is
# not None) is completely untouched by this fix — this file only
# exercises the pre-ticket branch, and test_attachment_upload_
# authorization.py / test_ticket_attachments.py already cover the
# ticketed path in full; this is a lightweight confirmation that the
# import/constant swap didn't accidentally affect the sibling branch's
# own gates (ensure_agent_can_view_ticket /
# ensure_account_manager_owns_ticket_client), which don't reference
# SUPERVISOR_ROLE_NAMES or GLOBAL_INBOX_ROLE_NAMES at all.
# ---------------------------------------------------------


async def test_ticketed_branch_untouched_grep_guard():
    import inspect

    from app.ticketing.services import attachment_service as attachment_service_module

    # The module no longer imports SUPERVISOR_ROLE_NAMES at all (its
    # only usage in this file was the one line narrowed by this fix) —
    # checked against the import list itself, not the function body's
    # own explanatory comment (which legitimately names the old
    # constant when describing what changed).
    assert not hasattr(attachment_service_module, "SUPERVISOR_ROLE_NAMES")
    assert hasattr(attachment_service_module, "GLOBAL_INBOX_ROLE_NAMES")

    source = inspect.getsource(AttachmentService._resolve_and_authorize)
    assert "current_user.role.name not in GLOBAL_INBOX_ROLE_NAMES" in source
    assert "ensure_agent_can_view_ticket" in source
    assert "ensure_account_manager_owns_ticket_client" in source
