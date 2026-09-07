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
from app.ticketing.services.company_signature_logo import COMPANY_LOGO_CONTENT_ID
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


# ---------------------------------------------------------------
# The system-managed company signature logo (see
# company_signature_logo.py) — unlike every other case above, this is
# the one attachment _finalize_envelope_attachments actively *adds*
# rather than merely validates, since there is deliberately no
# Attachment DB row/interaction ownership behind it.
# ---------------------------------------------------------------


def test_company_logo_is_attached_when_its_cid_is_present_in_body_html():
    envelope = _envelope(
        [], body_html=f'<div>Regards,<br>Jane</div><img src="cid:{COMPANY_LOGO_CONTENT_ID}">'
    )
    interaction = _FakeInteraction()

    result = InteractionService._finalize_envelope_attachments(interaction, envelope)

    assert len(result.attachments) == 1
    logo = result.attachments[0]
    assert logo.content_id == COMPANY_LOGO_CONTENT_ID
    assert logo.is_inline is True
    assert logo.content_base64  # real bytes, not empty
    # The correction was applied, so the persisted payload must reflect it.
    assert interaction.payload["envelope"] == result.model_dump()


def test_company_logo_is_not_attached_when_body_html_has_no_signature():
    """No signature (e.g. a user removed their whole signature block,
    or add_internal_note, which never calls this method at all) means
    no logo cid marker in body_html, so nothing is added — an exact
    no-op, byte-identical to every send path before this feature."""
    envelope = _envelope([], body_html="<p>Just a plain reply, no signature.</p>")
    interaction = _FakeInteraction()

    result = InteractionService._finalize_envelope_attachments(interaction, envelope)

    assert result.attachments == []
    assert result is envelope


def test_company_logo_is_not_duplicated_if_already_present():
    """Idempotent: calling this method twice (or an envelope that
    already carries the logo attachment for some reason) never adds a
    second copy."""
    existing_logo = EnvelopeAttachment(
        filename="probe-practice-solutions-logo.jpg",
        content_type="image/jpeg",
        content_base64="ZmFrZQ==",
        content_id=COMPANY_LOGO_CONTENT_ID,
        is_inline=True,
        attachment_id="system:company-logo",
    )
    envelope = _envelope(
        [existing_logo],
        body_html=f'<img src="cid:{COMPANY_LOGO_CONTENT_ID}">',
    )
    interaction = _FakeInteraction()

    result = InteractionService._finalize_envelope_attachments(interaction, envelope)

    assert result.attachments == [existing_logo]
    assert result is envelope  # no-op: already correct


def test_company_logo_coexists_with_a_genuine_pasted_inline_image():
    pasted = EnvelopeAttachment(
        filename="screenshot.png", content_type="image/png", content_base64="ZmFrZQ==",
        content_id="pasted-id", is_inline=True, attachment_id="att-pasted",
    )
    envelope = _envelope(
        [pasted],
        body_html=(
            '<p>See below.</p><img src="cid:pasted-id">'
            f'<div>Regards,<br>Jane</div><img src="cid:{COMPANY_LOGO_CONTENT_ID}">'
        ),
    )
    interaction = _FakeInteraction()

    result = InteractionService._finalize_envelope_attachments(interaction, envelope)

    assert len(result.attachments) == 2
    by_content_id = {a.content_id: a for a in result.attachments}
    assert by_content_id["pasted-id"].is_inline is True
    assert by_content_id[COMPANY_LOGO_CONTENT_ID].is_inline is True
