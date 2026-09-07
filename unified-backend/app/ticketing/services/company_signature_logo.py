# company_signature_logo.py
#
# The Probe Practice Solutions logo is a single, system-managed asset —
# not a per-user upload, and not part of any user's own editable
# User.signature_html (that field still rejects any <img> a user tries
# to save, see auth_service.py's update_profile). It is combined with a
# user's own signature text only at composer-render time on the
# frontend (see unified-frontend's richText.ts, buildSignatureBlockHtml)
# and re-attached here at send time, via the same `cid:`/inline-
# attachment mechanism every pasted composer image already uses —
# there is deliberately no Attachment DB row or AttachmentService
# upload behind it, since it isn't user data and needs no per-
# interaction ownership (see _finalize_envelope_attachments's own
# docstring for why that model doesn't fit a shared, reused asset).
#
# COMPANY_LOGO_CONTENT_ID must stay byte-identical to richText.ts's own
# copy of the same constant — it's the `cid:` value the frontend writes
# into outgoing body_html, and the value this module matches against to
# decide whether the logo attachment belongs on a given send.

import base64
from functools import lru_cache
from pathlib import Path

from app.ticketing.schemas.payloads import EnvelopeAttachment

COMPANY_LOGO_CONTENT_ID = "company-signature-logo-v1"

_LOGO_ATTACHMENT_ID = "system:company-logo"
_LOGO_FILENAME = "probe-practice-solutions-logo.jpg"
_LOGO_CONTENT_TYPE = "image/jpeg"
_LOGO_PATH = Path(__file__).resolve().parent.parent / "assets" / "company_logo.jpg"


@lru_cache(maxsize=1)
def _load_logo_base64() -> str:
    return base64.b64encode(_LOGO_PATH.read_bytes()).decode("ascii")


def build_company_logo_attachment() -> EnvelopeAttachment:
    """
    One inline EnvelopeAttachment for the company logo, ready to ride
    along on an outbound send exactly like a real pasted image would —
    see graph_client.py's _build_graph_attachments, which doesn't care
    whether an EnvelopeAttachment came from a real Attachment row or
    here. Safe to call on every send whose body_html references
    `cid:{COMPANY_LOGO_CONTENT_ID}` — the file itself is only ever read
    from disk once per process (lru_cache).
    """

    return EnvelopeAttachment(
        filename=_LOGO_FILENAME,
        content_type=_LOGO_CONTENT_TYPE,
        content_base64=_load_logo_base64(),
        attachment_id=_LOGO_ATTACHMENT_ID,
        content_id=COMPANY_LOGO_CONTENT_ID,
        is_inline=True,
    )
