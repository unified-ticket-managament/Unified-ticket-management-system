# test_finalize_envelope_attachments.py
#
# Pure-logic coverage for InteractionService._finalize_envelope_attachments
# — the additive safety net applied once, right before dispatch, after
# every _attach_outbound_files/_merge_existing_attachments_into_envelope/
# _merge_inline_images_into_envelope call has already run. See that
# method's own docstring for the two things it guards against: a
# literal duplicate Attachment row (by attachment_id) and an
# is_inline=True attachment whose content_id has no matching `cid:`
# anywhere in the final body_html (a stale pasted-image reference).
#
# No DB, no real envelope-building — OutboundEnvelope/EnvelopeAttachment
# are constructed directly, same convention as
# test_attachment_envelope_loading.py's in-memory Attachment rows.

from app.ticketing.schemas.payloads import EnvelopeAttachment, OutboundEnvelope
from app.ticketing.services.interaction_service import InteractionService


class _FakeInteraction:
    """Minimal stand-in — the method under test only reads/writes .payload."""

    def __init__(self):
        self.payload = {}


def _envelope(attachments: list[EnvelopeAttachment], body_html: str) -> OutboundEnvelope:
    return OutboundEnvelope(
        from_email="agent@example.com",
        to_email="client@example.com",
        subject="Test",
        message_id="<msg-1@example.com>",
        body="plain text body",
        body_html=body_html,
        attachments=attachments,
    )


def test_genuine_inline_image_with_matching_cid_is_untouched():
    attachment = EnvelopeAttachment(
        filename="logo.png",
        content_type="image/png",
        content_base64="ZmFrZQ==",
        content_id="abc123",
        is_inline=True,
        attachment_id="att-1",
    )
    envelope = _envelope([attachment], body_html='<p>Hi</p><img src="cid:abc123">')
    interaction = _FakeInteraction()

    result = InteractionService._finalize_envelope_attachments(interaction, envelope)

    assert result.attachments == [attachment]
    assert result is envelope  # no-op: nothing needed correcting


def test_genuine_normal_attachment_is_untouched():
    attachment = EnvelopeAttachment(
        filename="report.pdf",
        content_type="application/pdf",
        content_base64="ZmFrZQ==",
        is_inline=False,
        attachment_id="att-1",
    )
    envelope = _envelope([attachment], body_html="<p>See attached.</p>")
    interaction = _FakeInteraction()

    result = InteractionService._finalize_envelope_attachments(interaction, envelope)

    assert result.attachments == [attachment]


def test_two_distinct_inline_images_both_survive():
    a = EnvelopeAttachment(
        filename="a.png", content_type="image/png", content_base64="ZmFrZQ==",
        content_id="idA", is_inline=True, attachment_id="att-a",
    )
    b = EnvelopeAttachment(
        filename="b.png", content_type="image/png", content_base64="ZmFrZQ==",
        content_id="idB", is_inline=True, attachment_id="att-b",
    )
    envelope = _envelope(
        [a, b], body_html='<img src="cid:idA"><img src="cid:idB">'
    )
    interaction = _FakeInteraction()

    result = InteractionService._finalize_envelope_attachments(interaction, envelope)

    assert result.attachments == [a, b]


def test_similar_filenames_are_not_conflated_by_dedup():
    """Two distinct genuine attachments sharing a filename must both survive —
    dedup must key on attachment_id, never filename."""
    a = EnvelopeAttachment(
        filename="report.pdf", content_type="application/pdf",
        content_base64="ZmFrZQ==", is_inline=False, attachment_id="att-1",
    )
    b = EnvelopeAttachment(
        filename="report.pdf", content_type="application/pdf",
        content_base64="ZmFrZQ==", is_inline=False, attachment_id="att-2",
    )
    envelope = _envelope([a, b], body_html="<p>See attached.</p>")
    interaction = _FakeInteraction()

    result = InteractionService._finalize_envelope_attachments(interaction, envelope)

    assert result.attachments == [a, b]


def test_literal_duplicate_attachment_id_is_deduped():
    attachment = EnvelopeAttachment(
        filename="logo.png",
        content_type="image/png",
        content_base64="ZmFrZQ==",
        content_id="abc123",
        is_inline=True,
        attachment_id="att-1",
    )
    duplicate = attachment.model_copy()
    envelope = _envelope(
        [attachment, duplicate], body_html='<img src="cid:abc123">'
    )
    interaction = _FakeInteraction()

    result = InteractionService._finalize_envelope_attachments(interaction, envelope)

    assert len(result.attachments) == 1
    assert result.attachments[0].attachment_id == "att-1"
    # The correction was applied, so the persisted payload must reflect it.
    assert interaction.payload["envelope"] == result.model_dump()


def test_orphaned_inline_image_with_no_matching_cid_is_demoted_not_dropped():
    """The confirmed real-world case: a pasted image's interaction id
    survived in the composer's tracking state after the image itself
    was deleted/replaced before Send, so its content_id never actually
    appears in the final body_html. Must not be silently dropped
    (no attachment loss) — demoted to a normal attachment instead."""
    orphan = EnvelopeAttachment(
        filename="pasted-image.png",
        content_type="image/png",
        content_base64="ZmFrZQ==",
        content_id="stale-id",
        is_inline=True,
        attachment_id="att-orphan",
    )
    envelope = _envelope([orphan], body_html="<p>Hello, no image here.</p>")
    interaction = _FakeInteraction()

    result = InteractionService._finalize_envelope_attachments(interaction, envelope)

    assert len(result.attachments) == 1
    demoted = result.attachments[0]
    assert demoted.attachment_id == "att-orphan"
    assert demoted.is_inline is False
    assert demoted.content_id is None
    # Never dropped — the file content itself is preserved.
    assert demoted.content_base64 == "ZmFrZQ=="


def test_mixed_live_inline_and_orphaned_inline_and_normal_attachment():
    live_inline = EnvelopeAttachment(
        filename="live.png", content_type="image/png", content_base64="ZmFrZQ==",
        content_id="live-id", is_inline=True, attachment_id="att-live",
    )
    orphan = EnvelopeAttachment(
        filename="stale.png", content_type="image/png", content_base64="ZmFrZQ==",
        content_id="stale-id", is_inline=True, attachment_id="att-stale",
    )
    normal = EnvelopeAttachment(
        filename="report.pdf", content_type="application/pdf",
        content_base64="ZmFrZQ==", is_inline=False, attachment_id="att-normal",
    )
    envelope = _envelope(
        [live_inline, orphan, normal], body_html='<img src="cid:live-id">'
    )
    interaction = _FakeInteraction()

    result = InteractionService._finalize_envelope_attachments(interaction, envelope)

    assert len(result.attachments) == 3
    by_id = {a.attachment_id: a for a in result.attachments}
    assert by_id["att-live"].is_inline is True
    assert by_id["att-stale"].is_inline is False
    assert by_id["att-stale"].content_id is None
    assert by_id["att-normal"].is_inline is False
