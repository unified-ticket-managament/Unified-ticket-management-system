# test_interaction_service_attachment_load_error.py
#
# Phase 3: the "no silent attachment loss" fix — InteractionService
# catches AttachmentLoadError (raised by attachment_service.
# load_envelope_attachments when an attachment can't actually be
# embedded) at all three of its own call sites and converts it into a
# clean HTTPException(422), aborting the send, rather than letting an
# email go out silently missing an attachment. Exercises each private
# helper directly with minimal fakes — none of these three go through
# a real DB session or Graph call, only the specific attribute/method
# each helper itself touches before reaching load_envelope_attachments.

from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.ticketing.models.attachment import Attachment
from app.ticketing.models.interaction import Interaction
from app.ticketing.schemas.payloads import OutboundEnvelope
from app.ticketing.services import interaction_service as interaction_service_module
from app.ticketing.services.attachment_service import AttachmentLoadError, AttachmentService
from app.ticketing.services.interaction_service import InteractionService


def _service(**overrides) -> InteractionService:
    base = dict(
        interaction_repository=None,
        ticket_repository=None,
        user_repository=None,
        attachment_repository=object(),
        storage_service=object(),
    )
    base.update(overrides)
    return InteractionService(**base)


def _interaction() -> Interaction:
    return Interaction(interaction_id=uuid4(), payload={})


def _envelope() -> OutboundEnvelope:
    return OutboundEnvelope(
        from_email="agent@painmedpa.com",
        to_email="client@example.com",
        subject="Subject",
        message_id="msg-1",
        body="Hello",
    )


def _raise_attachment_load_error(monkeypatch):
    async def _raise(*args, **kwargs):
        raise AttachmentLoadError("could not load attachment")

    monkeypatch.setattr(interaction_service_module, "load_envelope_attachments", _raise)


async def test_attach_outbound_files_converts_attachment_load_error_to_422(monkeypatch):
    async def _fake_validate_and_store_files(self, files, interaction_id):
        return [Attachment(attachment_id=uuid4(), interaction_id=interaction_id)]

    monkeypatch.setattr(
        AttachmentService, "validate_and_store_files", _fake_validate_and_store_files
    )
    _raise_attachment_load_error(monkeypatch)

    service = _service()
    interaction = _interaction()
    envelope = _envelope()

    with pytest.raises(HTTPException) as exc_info:
        await service._attach_outbound_files(interaction, envelope, files=["fake-file"])

    assert exc_info.value.status_code == 422


async def test_merge_existing_attachments_converts_attachment_load_error_to_422(monkeypatch):
    class _FakeAttachmentRepository:
        async def list_by_interaction_id(self, interaction_id):
            return [Attachment(attachment_id=uuid4(), interaction_id=interaction_id)]

    _raise_attachment_load_error(monkeypatch)

    service = _service(attachment_repository=_FakeAttachmentRepository())
    interaction = _interaction()
    envelope = _envelope()

    with pytest.raises(HTTPException) as exc_info:
        await service._merge_existing_attachments_into_envelope(
            interaction, envelope, source_interaction_id=uuid4()
        )

    assert exc_info.value.status_code == 422


async def test_merge_inline_images_converts_attachment_load_error_to_422(monkeypatch):
    async def _fake_reassign(self, interaction, source_interaction_ids, **kwargs):
        return [Attachment(attachment_id=uuid4(), interaction_id=interaction.interaction_id)]

    monkeypatch.setattr(
        InteractionService, "_reassign_inline_image_interactions", _fake_reassign
    )
    _raise_attachment_load_error(monkeypatch)

    service = _service()
    interaction = _interaction()
    envelope = _envelope()

    with pytest.raises(HTTPException) as exc_info:
        await service._merge_inline_images_into_envelope(
            interaction, envelope, inline_image_interaction_ids=[uuid4()]
        )

    assert exc_info.value.status_code == 422
