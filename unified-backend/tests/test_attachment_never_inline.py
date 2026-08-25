# test_attachment_never_inline.py
#
# Phase 3: SVG (and any future NEVER_INLINE_EXTENSIONS member) must
# never be eligible for inline/preview rendering, even though its MIME
# type (image/svg+xml) otherwise matches attachment_to_metadata's
# "starts with image/" preview gate — a stored SVG served with
# Content-Disposition: inline via direct browser navigation (not an
# <img> tag) can execute embedded script. Pure-logic coverage, no DB,
# no real object storage.

from uuid import uuid4

from app.ticketing.models.attachment import Attachment
from app.ticketing.services.attachment_service import attachment_to_metadata


class _FakeStorageService:
    async def presigned_get_url(self, *, object_key: str, filename: str, inline: bool = False) -> str:
        return f"https://example.test/{object_key}?inline={inline}"


def _attachment(**overrides) -> Attachment:
    base = dict(
        attachment_id=uuid4(),
        interaction_id=uuid4(),
        filename="file.svg",
        mime_type="image/svg+xml",
        size_bytes=100,
        storage_key="attachments/file.svg",
        is_external_link=False,
    )
    base.update(overrides)
    return Attachment(**base)


async def test_svg_attachment_never_gets_a_preview_url():
    attachment = _attachment()
    storage = _FakeStorageService()

    metadata = await attachment_to_metadata(attachment, storage)

    assert metadata.preview_url is None


async def test_png_attachment_still_gets_a_preview_url():
    """Regression guard: the SVG carve-out must not disable inline
    preview for genuinely safe image types."""

    attachment = _attachment(filename="photo.png", mime_type="image/png")
    storage = _FakeStorageService()

    metadata = await attachment_to_metadata(attachment, storage)

    assert metadata.preview_url is not None
    assert "inline=True" in metadata.preview_url


async def test_spoofed_mime_type_on_a_non_image_extension_never_gets_a_preview_url():
    """
    P0 regression guard: a file whose filename extension is NOT an
    image type (so it was never subject to magic-byte sniffing —
    ATTACHMENT_MAGIC_SKIP_EXTENSIONS covers most non-image extensions)
    must never get an inline preview URL just because its declared
    mime_type claims to be an image. mime_type is attacker-controlled
    (upload Content-Type header, or an external sender's MIME headers
    on inbound mail) and is never verified against the extension for
    most types — trusting it for the inline/preview decision would let
    a same-origin-served "image/svg+xml" file with a non-.svg
    extension render via direct navigation, executing any embedded
    script (NEVER_INLINE_EXTENSIONS' whole reason to exist, bypassed).
    """
    attachment = _attachment(filename="payload.txt", mime_type="image/svg+xml")
    storage = _FakeStorageService()

    metadata = await attachment_to_metadata(attachment, storage)

    assert metadata.preview_url is None


async def test_honest_svg_extension_never_gets_a_preview_url_regardless_of_mime():
    """A real .svg file is never previewable even if its declared
    mime_type is something else entirely (e.g. a generic
    application/octet-stream) — the extension is what's authoritative."""
    attachment = _attachment(filename="signature.svg", mime_type="application/octet-stream")
    storage = _FakeStorageService()

    metadata = await attachment_to_metadata(attachment, storage)

    assert metadata.preview_url is None
