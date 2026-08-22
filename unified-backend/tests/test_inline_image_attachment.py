# test_inline_image_attachment.py
#
# Pure-logic coverage for AttachmentService.create_inline_image — the
# upload-time half of Outlook-style clipboard paste (pasted
# screenshots). No DB, no real object storage: mirrors
# test_attachment_envelope_loading.py's/test_attachment_upload_
# authorization.py's own fake conventions (a tiny in-memory
# StorageService fake, a minimal UploadFile stand-in) rather than
# hitting a real database.

from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.ticketing.models.attachment import Attachment
from app.ticketing.schemas.attachment import AttachmentCreate
from app.ticketing.services.attachment_service import (
    GRAPH_INLINE_ATTACHMENT_MAX_BYTES,
    AttachmentService,
)


class FakeUploadFile:
    """Minimal fastapi.UploadFile stand-in — mirrors the convention
    already established in test_attachment_upload_authorization.py."""

    def __init__(self, filename: str, content: bytes, content_type: str):
        self.filename = filename
        self.content_type = content_type
        self._content = content

    async def read(self) -> bytes:
        return self._content


class _FakeStorageService:
    bucket = "test-bucket"

    def __init__(self):
        self.uploaded: dict[str, bytes] = {}

    async def upload(self, *, data: bytes, object_key: str, content_type: str) -> None:
        self.uploaded[object_key] = data


class _FakeAttachmentRepository:
    def __init__(self):
        self.created: list[AttachmentCreate] = []

    async def create(self, data: AttachmentCreate) -> Attachment:
        self.created.append(data)
        return Attachment(**data.model_dump())


def _service(storage=None, attachment_repository=None) -> AttachmentService:
    return AttachmentService(
        attachment_repository=attachment_repository or _FakeAttachmentRepository(),
        interaction_repository=None,
        ticket_repository=None,
        storage_service=storage or _FakeStorageService(),
    )


async def test_create_inline_image_mints_a_content_id_and_sets_is_inline():
    service = _service()

    attachment = await service.create_inline_image(
        FakeUploadFile("screenshot.png", b"\x89PNG fake bytes", "image/png"),
        interaction_id="11111111-1111-1111-1111-111111111111",
    )

    assert attachment.is_inline is True
    assert attachment.content_id is not None
    assert len(attachment.content_id) > 0


async def test_create_inline_image_mints_a_unique_content_id_per_upload():
    service = _service()

    first = await service.create_inline_image(
        FakeUploadFile("a.png", b"aaa", "image/png"), interaction_id=uuid4()
    )
    second = await service.create_inline_image(
        FakeUploadFile("b.png", b"bbb", "image/png"), interaction_id=uuid4()
    )

    assert first.content_id != second.content_id


async def test_create_inline_image_stores_real_bytes_via_storage_service():
    storage = _FakeStorageService()
    service = _service(storage=storage)

    await service.create_inline_image(
        FakeUploadFile("screenshot.png", b"real-bytes-here", "image/png"),
        interaction_id=uuid4(),
    )

    assert b"real-bytes-here" in storage.uploaded.values()


async def test_create_inline_image_rejects_non_image_content_type():
    service = _service()

    with pytest.raises(HTTPException) as exc_info:
        await service.create_inline_image(
            FakeUploadFile("notes.pdf", b"%PDF", "application/pdf"),
            interaction_id=uuid4(),
        )

    assert exc_info.value.status_code == 415


async def test_create_inline_image_rejects_disallowed_extension():
    service = _service()

    with pytest.raises(HTTPException) as exc_info:
        await service.create_inline_image(
            FakeUploadFile("payload.exe", b"MZ", "image/png"),
            interaction_id=uuid4(),
        )

    assert exc_info.value.status_code == 415


async def test_create_inline_image_rejects_oversized_file():
    service = _service()
    oversized = b"x" * (GRAPH_INLINE_ATTACHMENT_MAX_BYTES + 1)

    with pytest.raises(HTTPException) as exc_info:
        await service.create_inline_image(
            FakeUploadFile("big.png", oversized, "image/png"),
            interaction_id=uuid4(),
        )

    assert exc_info.value.status_code == 413


async def test_create_inline_image_accepts_file_exactly_at_the_limit():
    service = _service()
    exactly_at_limit = b"x" * GRAPH_INLINE_ATTACHMENT_MAX_BYTES

    attachment = await service.create_inline_image(
        FakeUploadFile("at-limit.png", exactly_at_limit, "image/png"),
        interaction_id=uuid4(),
    )

    assert attachment.is_inline is True


class _FakeInboundInlineFile(FakeUploadFile):
    """
    Mirrors mail_mapping_service._GraphAttachmentUploadFile's shape for
    a real inbound Graph inline image — the same interface
    validate_and_store_files reads via getattr(..., default), not a
    special-cased type check.
    """

    def __init__(self, filename: str, content: bytes, content_type: str, content_id: str):
        super().__init__(filename, content, content_type)
        self.content_id = content_id
        self.is_inline = True


async def test_validate_and_store_files_persists_content_id_and_is_inline_when_present():
    """
    build_upload_files_from_graph_attachments (mail_mapping_service.py)
    hands validate_and_store_files a file object carrying its own
    content_id/is_inline — this is the one choke point that must
    actually persist them onto the resulting Attachment row, or an
    inbound pasted screenshot would be stored as an ordinary,
    non-resolvable attachment despite being correctly identified
    upstream.
    """

    service = _service()

    attachments = await service.validate_and_store_files(
        [_FakeInboundInlineFile("image001.png", b"\x89PNG", "image/png", "cid-from-graph")],
        interaction_id=uuid4(),
    )

    assert attachments[0].is_inline is True
    assert attachments[0].content_id == "cid-from-graph"


async def test_create_inline_image_never_folds_into_ordinary_attachment_flag():
    """
    validate_and_store_files (the ordinary batch-attachment path) must
    stay completely independent of create_inline_image — an ordinary
    attachment created through it should never accidentally end up
    is_inline=True just because both paths share the same repository/
    storage plumbing.
    """

    repo = _FakeAttachmentRepository()
    service = _service(attachment_repository=repo)

    ordinary = await service.validate_and_store_files(
        [FakeUploadFile("photo.png", b"abc", "image/png")],
        interaction_id=uuid4(),
    )

    assert ordinary[0].is_inline is False
    assert ordinary[0].content_id is None
