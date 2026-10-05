# test_attachment_download_voice_note.py
#
# INVESTIGATION / CHARACTERIZATION tests for GET /attachments/{id}/download
# (app/ticketing/api/attachment.py) with voice-note (audio) attachments.
#
# These pin the CURRENT backend behavior; no production code was changed
# to make them pass. PASS = the backend half of the download flow behaves
# correctly for that case. FAIL = the case reproduces the reported issue.
#
# Fully in-memory (no database, no network, no libmagic): the real route
# + real AttachmentService authorization/lookup logic run against fake
# repositories and a fake StorageService, via FastAPI's TestClient.

from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.database.session import get_db
from app.dependencies.auth import get_current_user
from app.ticketing.api import attachment as attachment_api
from app.ticketing.services.attachment_service import AttachmentService
from app.ticketing.storage.base import StorageService

# Real audio containers' leading bytes (not valid full files, but byte-exact
# round-trip is what the download path must preserve — including bytes that
# are not valid UTF-8 and a NUL, which would corrupt under any text handling).
AUDIO_BYTES = {
    "mp3": b"ID3\x03\x00\x00\x00\x00\x00\x21\xff\xfb\x90\x00" + bytes(range(256)),
    "wav": b"RIFF\x24\x08\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00" + bytes(range(256)),
    "m4a": b"\x00\x00\x00\x20ftypM4A \x00\x00\x00\x00" + bytes(range(256)),
    "ogg": b"OggS\x00\x02\x00\x00\x00\x00\x00\x00\x00\x00" + bytes(range(256)),
    "amr": b"#!AMR\n\x3c" + bytes(range(256)),
}

# (filename, mime_type stored on the Attachment row, extension key into AUDIO_BYTES)
VOICE_NOTE_CASES = [
    ("voicemail.mp3", "audio/mpeg", "mp3"),
    ("Voice_Message.wav", "audio/wav", "wav"),
    ("Voice_Message.wav", "audio/x-wav", "wav"),
    ("Voice_Memo.m4a", "audio/mp4", "m4a"),
    ("Voice_Memo.m4a", "audio/x-m4a", "m4a"),
    ("note.opus", "audio/ogg", "ogg"),
    ("note.opus", "audio/opus", "ogg"),
    ("recording.amr", "audio/amr", "amr"),
    ("recording.amr", "audio/3gpp", "amr"),
]


class FakeStorage(StorageService):
    bucket = "test-bucket"

    def __init__(self, objects=None, error=None):
        self.objects = objects or {}
        self.error = error

    async def upload(self, *, data, object_key, content_type):
        raise AssertionError("download path must never upload")

    async def download(self, *, object_key):
        if self.error is not None:
            raise self.error
        return self.objects[object_key]

    async def delete(self, *, object_key):
        raise AssertionError("download path must never delete")

    async def exists(self, *, object_key):
        return object_key in self.objects

    async def presigned_get_url(self, *, object_key, filename, inline=False):
        raise AssertionError("authenticated download must not use presigned URLs")


class FakeRepo:
    def __init__(self, rows):
        self.rows = rows

    async def get_by_id(self, row_id):
        return self.rows.get(row_id)


def _user(role="Super Admin", categories=()):
    return SimpleNamespace(
        user_id=uuid4(),
        name="Tester",
        role=SimpleNamespace(name=role),
        categories=[SimpleNamespace(category_name=c) for c in categories],
        permissions=[],
        scoped_permissions=[],
    )


def _build(*, filename, mime_type, content, user, ticket_type="AR", storage_error=None,
           is_external_link=False, storage_key="2026/10/abc-key"):
    attachment_id, interaction_id, ticket_id = uuid4(), uuid4(), uuid4()
    attachment = SimpleNamespace(
        attachment_id=attachment_id,
        interaction_id=interaction_id,
        filename=filename,
        mime_type=mime_type,
        size_bytes=len(content),
        storage_key=storage_key,
        is_external_link=is_external_link,
        external_url="https://example.invalid/x" if is_external_link else None,
    )
    interaction = SimpleNamespace(
        interaction_id=interaction_id, ticket_id=ticket_id, payload={}
    )
    ticket = SimpleNamespace(
        ticket_id=ticket_id, ticket_type=ticket_type, agent_id=None, client_id=None
    )
    storage = FakeStorage(
        objects={storage_key: content} if storage_key else {}, error=storage_error
    )
    service = AttachmentService(
        attachment_repository=FakeRepo({attachment_id: attachment}),
        interaction_repository=FakeRepo({interaction_id: interaction}),
        ticket_repository=FakeRepo({ticket_id: ticket}),
        storage_service=storage,
        client_repository=None,
    )

    app = FastAPI()
    app.include_router(attachment_api.router)
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_db] = lambda: None
    return app, service, attachment_id


@pytest.fixture
def patch_service(monkeypatch):
    def _apply(service):
        monkeypatch.setattr(attachment_api, "_build_service", lambda db: service)

    return _apply


@pytest.mark.parametrize("filename,mime_type,kind", VOICE_NOTE_CASES)
def test_voice_note_download_returns_exact_bytes_type_and_filename(
    patch_service, filename, mime_type, kind
):
    content = AUDIO_BYTES[kind]
    app, service, attachment_id = _build(
        filename=filename, mime_type=mime_type, content=content, user=_user()
    )
    patch_service(service)

    response = TestClient(app).get(f"/attachments/{attachment_id}/download")

    assert response.status_code == 200
    assert response.content == content  # byte-exact
    assert response.headers["content-type"] == mime_type  # no charset appended to audio/*
    assert response.headers["content-length"] == str(len(content))
    disposition = response.headers["content-disposition"]
    assert disposition.startswith("attachment;")
    assert f'filename="{filename}"' in disposition


def test_voice_note_with_no_stored_mime_type_falls_back_to_octet_stream(patch_service):
    content = AUDIO_BYTES["mp3"]
    app, service, attachment_id = _build(
        filename="voicemail.mp3", mime_type=None, content=content, user=_user()
    )
    patch_service(service)

    response = TestClient(app).get(f"/attachments/{attachment_id}/download")

    assert response.status_code == 200
    assert response.content == content
    assert response.headers["content-type"] == "application/octet-stream"


def test_non_ascii_filename_gets_ascii_fallback_and_rfc5987_name(patch_service):
    content = AUDIO_BYTES["m4a"]
    app, service, attachment_id = _build(
        filename="Voice café.m4a", mime_type="audio/mp4", content=content, user=_user()
    )
    patch_service(service)

    response = TestClient(app).get(f"/attachments/{attachment_id}/download")

    assert response.status_code == 200
    disposition = response.headers["content-disposition"]
    assert 'filename="Voice caf?.m4a"' in disposition
    assert "filename*=UTF-8''Voice%20caf%C3%A9.m4a" in disposition


def test_normal_pdf_download_still_works_same_path(patch_service):
    content = b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n" + bytes(range(256))
    app, service, attachment_id = _build(
        filename="invoice.pdf", mime_type="application/pdf", content=content, user=_user()
    )
    patch_service(service)

    response = TestClient(app).get(f"/attachments/{attachment_id}/download")

    assert response.status_code == 200
    assert response.content == content
    assert response.headers["content-type"] == "application/pdf"
    assert 'filename="invoice.pdf"' in response.headers["content-disposition"]


def test_missing_attachment_returns_404(patch_service):
    app, service, _ = _build(
        filename="v.mp3", mime_type="audio/mpeg", content=b"x", user=_user()
    )
    patch_service(service)

    response = TestClient(app).get(f"/attachments/{uuid4()}/download")

    assert response.status_code == 404


def test_unauthorized_team_lead_outside_category_gets_403(patch_service):
    app, service, attachment_id = _build(
        filename="v.mp3",
        mime_type="audio/mpeg",
        content=AUDIO_BYTES["mp3"],
        user=_user(role="Team Lead", categories=("Billing",)),
        ticket_type="AR",
    )
    patch_service(service)

    response = TestClient(app).get(f"/attachments/{attachment_id}/download")

    assert response.status_code == 403


def test_external_link_attachment_is_rejected_with_400(patch_service):
    app, service, attachment_id = _build(
        filename="v.mp3",
        mime_type="audio/mpeg",
        content=b"x",
        user=_user(),
        is_external_link=True,
        storage_key=None,
    )
    patch_service(service)

    response = TestClient(app).get(f"/attachments/{attachment_id}/download")

    assert response.status_code == 400


def test_storage_failure_currently_propagates_as_unhandled_exception(patch_service):
    """
    CHARACTERIZATION: when the storage object is missing/unreachable
    (S3 ClientError NoSuchKey / Supabase httpx.HTTPStatusError) the
    endpoint has no try/except, so the raw exception escapes -> HTTP 500
    with no domain-specific message (a clean 404/502 is never produced).
    """
    app, service, attachment_id = _build(
        filename="v.mp3",
        mime_type="audio/mpeg",
        content=b"x",
        user=_user(),
        storage_error=RuntimeError("NoSuchKey"),
    )
    patch_service(service)

    client = TestClient(app, raise_server_exceptions=False)
    response = client.get(f"/attachments/{attachment_id}/download")

    assert response.status_code == 500
