# signature_inline_images.py
#
# The `cid:` naming contract for user-uploaded signature images (see
# app/rbac/models/email_signature.py's EmailSignatureImage) — shared by
# the signature editor's save-time validation (EmailSignatureService)
# and the send path (InteractionService._attach_signature_images), so
# both sides agree on exactly one format.
#
# A signature image is referenced from signature/body HTML as
# `cid:sigimg-<32 hex>`, where the hex is the image's own image_id.
# SIGNATURE_IMAGE_CONTENT_ID_PREFIX must stay byte-identical to the
# frontend's copy in ticket-workspace/lib/signatures.ts.
#
# The content id is stable per image, not minted per message: images
# are immutable once uploaded (a new logo is a new row), so the same
# cid always names the same bytes — the same thing Outlook itself does
# for a signature logo reused across messages (see Attachment.
# content_id's own comment), and the same approach the system company
# logo (company_signature_logo.py) already takes. `content_id` only has
# to be unique within one message (ix_attachments_content_id), which a
# per-image id already guarantees.
#
# Signature images live under SIGNATURE_IMAGE_KEY_PREFIX in object
# storage. Each sent message that uses one gets an inline Attachment
# row sharing that same storage_key rather than a byte copy, so the
# attachment-deletion paths must never delete an object under this
# prefix — is_signature_image_storage_key is that check.

import re
from uuid import UUID

SIGNATURE_IMAGE_CONTENT_ID_PREFIX = "sigimg-"
SIGNATURE_IMAGE_KEY_PREFIX = "signature-images/"

_SIGNATURE_IMAGE_CID_PATTERN = re.compile(
    rf"cid:{SIGNATURE_IMAGE_CONTENT_ID_PREFIX}([0-9a-f]{{32}})\b",
    re.IGNORECASE,
)


def signature_image_content_id(image_id: UUID) -> str:
    return f"{SIGNATURE_IMAGE_CONTENT_ID_PREFIX}{image_id.hex}"


def referenced_signature_image_ids(html: str | None) -> list[UUID]:
    """
    Every distinct signature image referenced as `cid:sigimg-<hex>`
    in `html`, in first-seen order.
    """

    if not html:
        return []

    seen: dict[UUID, None] = {}
    for match in _SIGNATURE_IMAGE_CID_PATTERN.finditer(html):
        seen.setdefault(UUID(hex=match.group(1).lower()), None)
    return list(seen)


def is_signature_image_storage_key(storage_key: str | None) -> bool:
    return bool(storage_key) and storage_key.startswith(SIGNATURE_IMAGE_KEY_PREFIX)
