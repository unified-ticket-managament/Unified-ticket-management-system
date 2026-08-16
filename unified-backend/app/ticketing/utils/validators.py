# validators.py

import logging
import os
import re
import uuid
from datetime import datetime, timezone

from app.ticketing.utils.constants import ATTACHMENT_MIME_BY_EXTENSION

logger = logging.getLogger(__name__)

_UNSAFE_CHARS = re.compile(r"[^A-Za-z0-9._-]")


def sanitize_filename(filename: str) -> str:
    """
    Strips any directory component and replaces anything that isn't
    a safe filename character, so a client-supplied name can never
    escape the object-key prefix it's placed under.
    """
    base = os.path.basename(filename.replace("\\", "/")).strip()
    base = _UNSAFE_CHARS.sub("_", base)
    return base or "file"


def validate_attachment_type(filename: str, content_type: str | None) -> str:
    """
    Validates filename extension against the allow-list — the
    extension is the actual security gate. `content_type` is advisory
    only: a present-but-unexpected value (e.g. a generic
    "application/octet-stream", or any other mismatch) is logged but
    no longer rejected, since a declared MIME type is an unreliable
    signal from real-world senders/relays and must never override an
    otherwise-allowed extension. Returns the lowercase extension on
    success, raises ValueError with a user-facing message only when
    the extension itself isn't recognized.
    """
    extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    allowed_mimes = ATTACHMENT_MIME_BY_EXTENSION.get(extension)

    if allowed_mimes is None:
        raise ValueError(f'"{filename}" has an unsupported file type.')

    if content_type and content_type not in allowed_mimes:
        logger.info(
            "%r declared content_type %r doesn't match expected %s for .%s — "
            "accepting based on the extension allow-list alone",
            filename,
            content_type,
            sorted(allowed_mimes),
            extension,
        )

    return extension


def build_attachment_object_key(sanitized_filename: str) -> str:
    now = datetime.now(timezone.utc)
    return f"{now.year:04d}/{now.month:02d}/{uuid.uuid4()}-{sanitized_filename}"
