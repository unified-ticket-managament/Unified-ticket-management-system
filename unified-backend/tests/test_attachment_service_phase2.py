# test_attachment_service_phase2.py
#
# Phase 2 hardening coverage:
# - Attachment.scan_status defaults to "not_scanned", not the old
#   misleading "pending" (no AV scan exists or is implied).
# - The attachment size-limit error message is derived from the real
#   MAX_ATTACHMENT_SIZE_BYTES constant (30MB), not a stale hardcoded
#   "25MB" string that could drift from the actual enforced limit.
#
# The scan_status check runs against the real (dev) database inside a
# transaction rolled back at the end, same convention as
# test_attachment_upload_authorization.py. The size-limit check is pure
# service-logic — no DB, no real storage upload (the size check raises
# before either would be touched).

import io
import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.database.session import AsyncSessionLocal, engine
from app.ticketing.enums import InteractionDirection, InteractionStatus
from app.ticketing.models.attachment import Attachment
from app.ticketing.models.interaction import Interaction
from app.ticketing.repositories.attachment_repository import AttachmentRepository
from app.ticketing.schemas.attachment import AttachmentCreate
from app.ticketing.services.attachment_service import AttachmentService
from app.ticketing.utils.constants import MAX_ATTACHMENT_SIZE_BYTES


@pytest.fixture
async def db_session():
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.rollback()
    await engine.dispose()


async def _make_bare_interaction(session) -> uuid.UUID:
    interaction_id = uuid.uuid4()
    session.add(
        Interaction(
            interaction_id=interaction_id,
            interaction_type="ATTACHMENT",
            status=InteractionStatus.ASSIGNED,
            direction=InteractionDirection.INTERNAL,
            payload={},
            is_visible=True,
        )
    )
    await session.flush()
    return interaction_id


async def test_new_attachment_defaults_to_not_scanned(db_session):
    interaction_id = await _make_bare_interaction(db_session)
    repo = AttachmentRepository(db_session)

    attachment = await repo.create(
        AttachmentCreate(
            interaction_id=interaction_id,
            filename="report.pdf",
            mime_type="application/pdf",
            size_bytes=1234,
            storage_key="some/key.pdf",
        )
    )

    assert attachment.scan_status == "not_scanned"

    # Confirm it round-trips from the DB the same way, not just the
    # in-memory object right after insert.
    reloaded = (
        await db_session.execute(
            select(Attachment).where(Attachment.attachment_id == attachment.attachment_id)
        )
    ).scalar_one()
    assert reloaded.scan_status == "not_scanned"


class _FakeUploadFile:
    def __init__(self, filename: str, content: bytes, content_type: str):
        self.filename = filename
        self.content_type = content_type
        self._content = content

    async def read(self) -> bytes:
        return self._content


async def test_oversized_attachment_error_message_matches_real_limit():
    """
    The real bug: the error string said "25MB" while
    MAX_ATTACHMENT_SIZE_BYTES is actually 30MB. Deriving the message
    from the constant means it can never drift again.
    """

    service = AttachmentService(
        attachment_repository=None,
        interaction_repository=None,
        ticket_repository=None,
        storage_service=None,
    )

    oversized_content = b"x" * (MAX_ATTACHMENT_SIZE_BYTES + 1)
    file = _FakeUploadFile("big.pdf", oversized_content, "application/pdf")

    with pytest.raises(HTTPException) as exc_info:
        await service.validate_and_store_files([file], uuid.uuid4())

    assert exc_info.value.status_code == 413
    expected_mb = MAX_ATTACHMENT_SIZE_BYTES // (1024 * 1024)
    assert f"{expected_mb}MB" in exc_info.value.detail
    assert "25MB" not in exc_info.value.detail
