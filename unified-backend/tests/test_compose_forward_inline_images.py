# test_compose_forward_inline_images.py
#
# Pure-logic coverage for the Compose/Forward inline-image staging
# mechanism added alongside Reply's own (pre-existing) support — no
# DB, no real object storage, no real network. Mirrors the fake-
# repository conventions already established in
# test_inline_image_attachment.py / test_forward_to_internal_user.py.
#
# Focus: InteractionService.upload_compose_inline_image mints a real,
# ticketless, current-user-owned staging interaction (the thing
# neither Compose nor Forward had before this feature), and
# _reassign_inline_image_interactions/_merge_inline_images_into_
# envelope's new expected_performed_by check is the one thing standing
# between "this screenshot belongs to me" and a crafted request
# stealing someone else's staged image the way expected_ticket_id
# already protects the ticket-scoped Reply/Note case.

from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.ticketing.schemas.attachment import AttachmentCreate
from app.ticketing.schemas.interaction import InteractionCreate, InteractionUpdate
from app.ticketing.services.email_envelope import build_compose_envelope
from app.ticketing.services.interaction_service import InteractionService


class _FakeUser:
    def __init__(self, user_id, name="Agent"):
        self.user_id = user_id
        self.name = name


class _FakeInteraction:
    """Stands in for both a freshly-created staging interaction and an
    already-existing one looked up by id."""

    def __init__(self, interaction_id, ticket_id, performed_by, payload=None):
        self.interaction_id = interaction_id
        self.ticket_id = ticket_id
        self.performed_by = performed_by
        self.payload = payload or {}
        self.is_visible = True


class _FakeInteractionRepository:
    def __init__(self, existing: list[_FakeInteraction] | None = None):
        self._by_id = {i.interaction_id: i for i in (existing or [])}
        self.created: list[_FakeInteraction] = []
        self.updated: list[tuple] = []

    async def get_by_id(self, interaction_id):
        return self._by_id.get(interaction_id)

    async def create(self, data: InteractionCreate):
        interaction = _FakeInteraction(
            interaction_id=uuid4(),
            ticket_id=data.ticket_id,
            performed_by=data.performed_by,
            payload=data.payload,
        )
        self._by_id[interaction.interaction_id] = interaction
        self.created.append(interaction)
        return interaction

    async def update(self, interaction, data: InteractionUpdate):
        self.updated.append((interaction.interaction_id, data))
        if data.is_visible is not None:
            interaction.is_visible = data.is_visible
        return interaction


class _FakeAttachment:
    def __init__(self, attachment_id, interaction_id, content_id, is_inline, storage_key, mime_type, size_bytes, bucket_name, filename):
        self.attachment_id = attachment_id
        self.interaction_id = interaction_id
        self.content_id = content_id
        self.is_inline = is_inline
        self.storage_key = storage_key
        self.mime_type = mime_type
        self.size_bytes = size_bytes
        self.bucket_name = bucket_name
        self.filename = filename
        self.is_external_link = False
        self.external_url = None


class _FakeAttachmentRepository:
    def __init__(self):
        self._rows: list[_FakeAttachment] = []
        self.reassigned: list[tuple] = []

    async def create(self, data: AttachmentCreate):
        attachment = _FakeAttachment(
            attachment_id=uuid4(),
            interaction_id=data.interaction_id,
            content_id=data.content_id,
            is_inline=data.is_inline,
            storage_key=data.storage_key,
            mime_type=data.mime_type,
            size_bytes=data.size_bytes,
            bucket_name=data.bucket_name,
            filename=data.filename,
        )
        self._rows.append(attachment)
        return attachment

    async def list_by_interaction_id(self, interaction_id):
        return [row for row in self._rows if row.interaction_id == interaction_id]

    async def reassign_interaction(self, source_interaction_id, target_interaction_id):
        self.reassigned.append((source_interaction_id, target_interaction_id))
        for row in self._rows:
            if row.interaction_id == source_interaction_id:
                row.interaction_id = target_interaction_id


class _FakeStorageService:
    bucket = "test-bucket"

    def __init__(self):
        self.uploaded: dict[str, bytes] = {}

    async def upload(self, *, data, object_key, content_type):
        self.uploaded[object_key] = data

    async def download(self, *, object_key):
        return self.uploaded.get(object_key, b"")

    async def presigned_get_url(self, *, object_key, filename, inline):
        return f"https://example.com/{object_key}"


class FakeUploadFile:
    def __init__(self, filename: str, content: bytes, content_type: str):
        self.filename = filename
        self.content_type = content_type
        self._content = content

    async def read(self) -> bytes:
        return self._content


def _service(interaction_repository=None, attachment_repository=None, storage=None):
    return InteractionService(
        interaction_repository=interaction_repository or _FakeInteractionRepository(),
        ticket_repository=None,
        user_repository=None,
        client_repository=None,
        attachment_repository=attachment_repository or _FakeAttachmentRepository(),
        storage_service=storage or _FakeStorageService(),
    )


async def test_upload_compose_inline_image_stages_a_ticketless_owned_interaction():
    """
    Neither Compose nor Forward has a pre-existing interaction to
    upload a pasted screenshot against before Send — this is the one
    method that makes that possible, by minting a minimal standalone
    interaction (no ticket_id) owned by the uploading user.
    """

    interaction_repo = _FakeInteractionRepository()
    attachment_repo = _FakeAttachmentRepository()
    service = _service(interaction_repository=interaction_repo, attachment_repository=attachment_repo)
    current_user = _FakeUser(uuid4())

    result = await service.upload_compose_inline_image(
        FakeUploadFile("screenshot.png", b"\x89PNG fake bytes", "image/png"),
        current_user,
    )

    assert result.content_id is not None
    assert result.interaction_id is not None

    staged = interaction_repo.created[0]
    assert staged.ticket_id is None
    assert staged.performed_by == current_user.user_id
    assert result.interaction_id == staged.interaction_id

    stored = attachment_repo._rows[0]
    assert stored.is_inline is True
    assert stored.interaction_id == staged.interaction_id


def _real_envelope():
    return build_compose_envelope(
        from_email="client@probeps.com",
        to_email="recipient@example.com",
        subject="Test",
        body="hello",
        cc=[],
        bcc=[],
        agent_name="Agent Name",
    )


async def test_merge_inline_images_accepts_own_staged_interaction():
    """
    The happy path: a screenshot staged by upload_compose_inline_image
    and then referenced by the same user at Send time is reassigned
    onto the real outbound interaction and embedded in the envelope.
    """

    uploader_id = uuid4()
    staged = _FakeInteraction(interaction_id=uuid4(), ticket_id=None, performed_by=uploader_id)
    interaction_repo = _FakeInteractionRepository(existing=[staged])
    attachment_repo = _FakeAttachmentRepository()
    await attachment_repo.create(
        AttachmentCreate(
            interaction_id=staged.interaction_id,
            filename="screenshot.png",
            mime_type="image/png",
            size_bytes=10,
            storage_key="k",
            bucket_name="b",
            content_id="cid-123",
            is_inline=True,
        )
    )
    service = _service(interaction_repository=interaction_repo, attachment_repository=attachment_repo)

    composed_interaction = _FakeInteraction(interaction_id=uuid4(), ticket_id=None, performed_by=uploader_id)

    envelope = await service._merge_inline_images_into_envelope(
        composed_interaction,
        _real_envelope(),
        [staged.interaction_id],
        expected_performed_by=uploader_id,
    )

    assert len(envelope.attachments) == 1
    assert envelope.attachments[0].content_id == "cid-123"
    # The staging interaction's attachment is reassigned onto the real
    # outbound interaction, and the now-empty staging interaction is
    # hidden — same convention Reply's own reassignment already uses.
    assert attachment_repo.reassigned == [(staged.interaction_id, composed_interaction.interaction_id)]
    assert staged.is_visible is False


async def test_merge_inline_images_rejects_someone_elses_staged_interaction():
    """
    Without this check, a crafted inline_image_interaction_ids value
    could reference another user's staged screenshot (there's no
    ticket to scope against for Compose/Forward, unlike Reply/Note) and
    have it silently embedded in this user's outbound email.
    """

    uploader_id = uuid4()
    attacker_id = uuid4()
    staged = _FakeInteraction(interaction_id=uuid4(), ticket_id=None, performed_by=uploader_id)
    interaction_repo = _FakeInteractionRepository(existing=[staged])
    service = _service(interaction_repository=interaction_repo)

    composed_interaction = _FakeInteraction(interaction_id=uuid4(), ticket_id=None, performed_by=attacker_id)

    with pytest.raises(HTTPException) as exc_info:
        await service._merge_inline_images_into_envelope(
            composed_interaction,
            _real_envelope(),
            [staged.interaction_id],
            expected_performed_by=attacker_id,
        )

    assert exc_info.value.status_code == 400


async def test_merge_inline_images_is_a_no_op_with_no_ids():
    service = _service()
    composed_interaction = _FakeInteraction(interaction_id=uuid4(), ticket_id=None, performed_by=uuid4())
    envelope = _real_envelope()

    result = await service._merge_inline_images_into_envelope(
        composed_interaction, envelope, [], expected_performed_by=uuid4()
    )

    assert result is envelope
