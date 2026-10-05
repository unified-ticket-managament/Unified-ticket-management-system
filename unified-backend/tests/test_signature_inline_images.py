# test_signature_inline_images.py
#
# Send-time coverage for user-uploaded signature images — no DB, no
# real storage, no network. InteractionService._attach_signature_images
# turns every `cid:sigimg-<hex>` in an outgoing body into a true inline
# MIME part (an Attachment row sharing the image's storage object, then
# a Graph fileAttachment with isInline/contentId), exactly the way the
# company logo and pasted screenshots already reach Graph.

import base64
from types import SimpleNamespace
from uuid import uuid4

from app.ticketing.schemas.attachment import AttachmentCreate
from app.ticketing.services.email_envelope import build_compose_envelope, build_reply_envelope
from app.ticketing.services.graph_client import _build_graph_attachments, _build_reply_action_body
from app.ticketing.services.interaction_service import InteractionService
from app.ticketing.services.signature_inline_images import (
    SIGNATURE_IMAGE_KEY_PREFIX,
    referenced_signature_image_ids,
    signature_image_content_id,
)
from app.ticketing.schemas.payloads import EmailPayload, EnvelopeAttachment

PNG = b"\x89PNG\r\n\x1a\n" + b"\x01" * 32


class _FakeAttachmentRepository:
    def __init__(self):
        self.rows = []
        self.deleted = []

    async def create(self, data: AttachmentCreate):
        row = SimpleNamespace(attachment_id=uuid4(), **data.model_dump())
        self.rows.append(row)
        return row

    async def list_by_interaction_id(self, interaction_id):
        return [r for r in self.rows if r.interaction_id == interaction_id]

    async def delete(self, row):
        self.deleted.append(row)
        self.rows.remove(row)


class _FakeStorage:
    bucket = "test-bucket"

    def __init__(self):
        self.objects: dict[str, bytes] = {}
        self.deleted: list[str] = []

    async def download(self, *, object_key):
        return self.objects[object_key]

    async def delete(self, *, object_key):
        self.deleted.append(object_key)


class _FakeSignatureImageRepository:
    def __init__(self, images):
        self.images = images

    async def list_images_by_ids(self, user_id, image_ids):
        return [i for i in self.images if i.user_id == user_id and i.image_id in image_ids]


def _image(storage, user_id, filename="logo.png"):
    image_id = uuid4()
    key = f"{SIGNATURE_IMAGE_KEY_PREFIX}{user_id}/{image_id}-{filename}"
    storage.objects[key] = PNG
    return SimpleNamespace(
        image_id=image_id,
        user_id=user_id,
        filename=filename,
        mime_type="image/png",
        size_bytes=len(PNG),
        storage_key=key,
        bucket_name="test-bucket",
    )


def _service(images, storage):
    attachments = _FakeAttachmentRepository()
    service = InteractionService(
        interaction_repository=SimpleNamespace(db=None),
        ticket_repository=None,
        user_repository=None,
        attachment_repository=attachments,
        storage_service=storage,
        signature_image_repository=_FakeSignatureImageRepository(images),
    )
    return service, attachments


def _interaction():
    return SimpleNamespace(interaction_id=uuid4(), payload={})


def _signed_body(*images, marker=True):
    imgs = "".join(
        f'<img src="cid:{signature_image_content_id(i.image_id)}" width="120">' for i in images
    )
    wrapper = '<div data-utms-signature="abc">' if marker else "<div>"
    return f"<p>Hello,</p><p>Details below.</p>{wrapper}<p>Regards,<br>Hari</p><p>{imgs}</p></div>"


def _compose(body_html):
    return build_compose_envelope(
        from_email="support@probeps.com",
        to_email="client@example.com",
        subject="Hi",
        body="Hello",
        body_html=body_html,
    )


async def test_signature_image_becomes_inline_attachment_not_regular_file():
    storage = _FakeStorage()
    user_id = uuid4()
    logo = _image(storage, user_id)
    service, attachments = _service([logo], storage)
    interaction = _interaction()

    envelope = await service._attach_signature_images(
        interaction, _compose(_signed_body(logo)), user_id
    )
    envelope = service._finalize_envelope_attachments(interaction, envelope)

    content_id = signature_image_content_id(logo.image_id)
    assert content_id == f"sigimg-{logo.image_id.hex}"
    [attachment] = envelope.attachments
    assert attachment.is_inline is True
    assert attachment.content_id == content_id
    assert base64.b64decode(attachment.content_base64) == PNG
    # Shares the image's stored object — no per-email byte copy.
    [row] = attachments.rows
    assert row.storage_key == logo.storage_key and row.is_inline is True
    assert row.interaction_id == interaction.interaction_id
    # Persisted envelope (what the delayed dispatcher sends) matches.
    assert interaction.payload["envelope"]["attachments"][0]["content_id"] == content_id

    [graph_item] = _build_graph_attachments(envelope.attachments)
    assert graph_item["isInline"] is True
    assert graph_item["contentId"] == content_id
    assert graph_item["contentType"] == "image/png"
    assert f'src="cid:{content_id}"' in envelope.body_html


async def test_multiple_signature_images_are_all_inline():
    storage = _FakeStorage()
    user_id = uuid4()
    probe = _image(storage, user_id, "probe.png")
    partner = _image(storage, user_id, "partner.png")
    service, _ = _service([probe, partner], storage)
    interaction = _interaction()

    envelope = await service._attach_signature_images(
        interaction, _compose(_signed_body(probe, partner)), user_id
    )
    envelope = service._finalize_envelope_attachments(interaction, envelope)

    assert [a.content_id for a in envelope.attachments] == [
        signature_image_content_id(probe.image_id),
        signature_image_content_id(partner.image_id),
    ]
    assert all(a.is_inline for a in envelope.attachments)
    assert all(item["isInline"] for item in _build_graph_attachments(envelope.attachments))


async def test_reply_carries_signature_image_inline_above_graph_quote():
    storage = _FakeStorage()
    user_id = uuid4()
    logo = _image(storage, user_id)
    service, _ = _service([logo], storage)
    interaction = _interaction()
    reply = build_reply_envelope(
        from_email="support@probeps.com",
        inbound_payload=EmailPayload(
            to_email="support@probeps.com", from_email="john@client.com", subject="Claim", body="?"
        ),
        inbound_message_id="<orig@client.com>",
        body="My reply",
        body_html=_signed_body(logo),
        reply_to_provider_message_id="AAMk-original",
    )

    envelope = await service._attach_signature_images(interaction, reply, user_id)
    body = _build_reply_action_body(envelope)

    # Graph's reply action quotes the original BELOW `comment`, so the
    # signature (part of comment) always lands above the quote.
    assert "Regards" in body["comment"]
    assert body["message"]["attachments"][0]["isInline"] is True


async def test_another_users_image_is_never_embedded():
    storage = _FakeStorage()
    owner, sender = uuid4(), uuid4()
    foreign = _image(storage, owner)
    service, attachments = _service([foreign], storage)

    envelope = await service._attach_signature_images(
        _interaction(), _compose(_signed_body(foreign)), sender
    )

    assert envelope.attachments == []
    assert attachments.rows == []


async def test_image_already_carried_by_envelope_is_not_duplicated():
    storage = _FakeStorage()
    user_id = uuid4()
    logo = _image(storage, user_id)
    service, attachments = _service([logo], storage)
    content_id = signature_image_content_id(logo.image_id)
    envelope = _compose(_signed_body(logo)).model_copy(
        update={
            "attachments": [
                EnvelopeAttachment(
                    filename="logo.png",
                    content_type="image/png",
                    content_base64=base64.b64encode(PNG).decode(),
                    attachment_id=str(uuid4()),
                    content_id=content_id,
                    is_inline=True,
                )
            ]
        }
    )

    result = await service._attach_signature_images(_interaction(), envelope, user_id)

    assert [a.content_id for a in result.attachments] == [content_id]
    assert attachments.rows == []


async def test_body_without_signature_images_is_untouched():
    storage = _FakeStorage()
    service, attachments = _service([], storage)
    envelope = _compose("<p>Plain reply</p>")

    assert await service._attach_signature_images(_interaction(), envelope, uuid4()) is envelope
    assert attachments.rows == []


def test_composer_signature_marker_never_reaches_recipient():
    envelope = _compose(_signed_body(marker=True))
    assert "data-utms-signature" not in envelope.body_html
    assert "Regards" in envelope.body_html


def test_referenced_signature_image_ids_parses_and_dedupes():
    a, b = uuid4(), uuid4()
    html = (
        f'<img src="cid:sigimg-{a.hex}"><img src="CID:SIGIMG-{b.hex.upper()}">'
        f'<img src="cid:sigimg-{a.hex}"><img src="cid:sigimg-nothex">'
        '<img src="cid:company-signature-logo-v1">'
    )
    assert referenced_signature_image_ids(html) == [a, b]


async def test_discarding_rows_never_deletes_a_shared_signature_image_object():
    storage = _FakeStorage()
    service, attachments = _service([], storage)
    interaction_id = uuid4()
    shared_key = f"{SIGNATURE_IMAGE_KEY_PREFIX}{uuid4()}/logo.png"
    pasted_key = "2026/10/pasted.png"
    for key in (shared_key, pasted_key):
        await attachments.create(
            AttachmentCreate(
                interaction_id=interaction_id,
                filename="x.png",
                mime_type="image/png",
                size_bytes=1,
                storage_key=key,
                bucket_name="b",
                content_id=uuid4().hex,
                is_inline=True,
            )
        )

    await service._delete_stored_attachments(interaction_id)

    assert storage.deleted == [pasted_key]
    assert attachments.rows == []
