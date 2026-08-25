# test_attachment_envelope_loading.py
#
# Pure-logic coverage for attachment_service.load_envelope_attachments
# — the piece that reads a stored attachment's real bytes back out
# and base64-encodes them for inline embedding in an outbound Graph
# sendMail call. No DB, no real object storage: Attachment rows are
# constructed in-memory (never flushed) and StorageService is a tiny
# in-memory fake.

import base64
from uuid import uuid4

import pytest

from app.ticketing.models.attachment import Attachment
from app.ticketing.services.attachment_service import (
    GRAPH_INLINE_ATTACHMENT_MAX_BYTES,
    AttachmentLoadError,
    load_envelope_attachments,
)


class _FakeStorageService:
    def __init__(self, objects: dict):
        self._objects = objects

    async def download(self, *, object_key: str) -> bytes:
        if object_key not in self._objects:
            raise FileNotFoundError(object_key)
        return self._objects[object_key]


def _attachment(**overrides) -> Attachment:
    base = dict(
        attachment_id=uuid4(),
        interaction_id=uuid4(),
        filename="notes.txt",
        mime_type="text/plain",
        size_bytes=5,
        storage_key="attachments/notes.txt",
    )
    base.update(overrides)
    return Attachment(**base)


async def test_load_envelope_attachments_base64_encodes_content():
    attachment = _attachment(storage_key="k1", size_bytes=5)
    storage = _FakeStorageService({"k1": b"hello"})

    loaded = await load_envelope_attachments([attachment], storage)

    assert len(loaded) == 1
    assert loaded[0].filename == "notes.txt"
    assert loaded[0].content_type == "text/plain"
    assert base64.b64decode(loaded[0].content_base64) == b"hello"


async def test_load_envelope_attachments_falls_back_to_octet_stream_mime_type():
    attachment = _attachment(storage_key="k1", mime_type=None)
    storage = _FakeStorageService({"k1": b"hello"})

    loaded = await load_envelope_attachments([attachment], storage)

    assert loaded[0].content_type == "application/octet-stream"


async def test_load_envelope_attachments_defers_oversized_file_with_storage_key():
    """
    An oversized attachment that DOES have a storage_key is deferred
    to a Graph upload session (a lightweight storage_key reference),
    not an error — this is the normal large-attachment path, distinct
    from the no-storage-key failure case below.
    """

    attachment = _attachment(
        storage_key="big", size_bytes=GRAPH_INLINE_ATTACHMENT_MAX_BYTES + 1
    )
    storage = _FakeStorageService({"big": b"x" * 10})

    loaded = await load_envelope_attachments([attachment], storage)

    assert len(loaded) == 1
    assert loaded[0].storage_key == "big"
    assert loaded[0].content_base64 is None


async def test_load_envelope_attachments_raises_on_oversized_file_with_no_storage_key():
    """
    An oversized attachment with no storage_key at all can't be
    embedded inline or deferred to an upload session — this must abort
    the send with a clear error (AttachmentLoadError), never silently
    send without it.
    """

    attachment = _attachment(
        storage_key=None, size_bytes=GRAPH_INLINE_ATTACHMENT_MAX_BYTES + 1
    )
    storage = _FakeStorageService({})

    with pytest.raises(AttachmentLoadError):
        await load_envelope_attachments([attachment], storage)


async def test_load_envelope_attachments_raises_when_download_fails():
    attachment = _attachment(storage_key="missing")
    storage = _FakeStorageService({})

    with pytest.raises(AttachmentLoadError):
        await load_envelope_attachments([attachment], storage)


async def test_load_envelope_attachments_aborts_entirely_on_one_bad_attachment():
    """
    Fail-loud is all-or-nothing: a good attachment alongside one that
    can't be loaded must abort the whole call (no partial success),
    since a caller catching AttachmentLoadError aborts the send before
    anything is committed.
    """

    good = _attachment(storage_key="good", filename="a.txt", size_bytes=5)
    unloadable = _attachment(storage_key="missing", filename="b.txt", size_bytes=5)
    storage = _FakeStorageService({"good": b"hello"})

    with pytest.raises(AttachmentLoadError):
        await load_envelope_attachments([good, unloadable], storage)


async def test_load_envelope_attachments_still_succeeds_for_all_valid_attachments():
    small = _attachment(storage_key="good", filename="a.txt", size_bytes=5)
    large = _attachment(
        storage_key="big",
        filename="b.zip",
        size_bytes=GRAPH_INLINE_ATTACHMENT_MAX_BYTES + 1,
    )
    storage = _FakeStorageService({"good": b"hello", "big": b"x"})

    loaded = await load_envelope_attachments([small, large], storage)

    assert len(loaded) == 2
    assert {item.filename for item in loaded} == {"a.txt", "b.zip"}
