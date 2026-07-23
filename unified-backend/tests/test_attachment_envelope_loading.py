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

from app.ticketing.models.attachment import Attachment
from app.ticketing.services.attachment_service import (
    GRAPH_INLINE_ATTACHMENT_MAX_BYTES,
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


async def test_load_envelope_attachments_skips_oversized_file():
    """
    Graph's sendMail only accepts small inline attachments — an
    oversized one must be dropped (logged, not raised) rather than
    failing the whole send.
    """

    attachment = _attachment(
        storage_key="big", size_bytes=GRAPH_INLINE_ATTACHMENT_MAX_BYTES + 1
    )
    storage = _FakeStorageService({"big": b"x" * 10})

    loaded = await load_envelope_attachments([attachment], storage)

    assert loaded == []


async def test_load_envelope_attachments_skips_file_that_fails_to_download():
    attachment = _attachment(storage_key="missing")
    storage = _FakeStorageService({})

    loaded = await load_envelope_attachments([attachment], storage)

    assert loaded == []


async def test_load_envelope_attachments_handles_multiple_files_independently():
    good = _attachment(storage_key="good", filename="a.txt", size_bytes=5)
    oversized = _attachment(
        storage_key="big", filename="b.zip", size_bytes=GRAPH_INLINE_ATTACHMENT_MAX_BYTES + 1
    )
    storage = _FakeStorageService({"good": b"hello", "big": b"x"})

    loaded = await load_envelope_attachments([good, oversized], storage)

    assert len(loaded) == 1
    assert loaded[0].filename == "a.txt"
