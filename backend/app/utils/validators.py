# validators.py

import os
import re
import uuid
from datetime import datetime, timezone

from app.utils.constants import ATTACHMENT_MIME_BY_EXTENSION

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
    Validates filename extension + MIME type against the allow-list.
    Returns the lowercase extension on success, raises ValueError
    with a user-facing message otherwise.
    """
    extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    allowed_mimes = ATTACHMENT_MIME_BY_EXTENSION.get(extension)

    if allowed_mimes is None:
        raise ValueError(f'"{filename}" has an unsupported file type.')

    if content_type and content_type not in allowed_mimes:
        raise ValueError(f'"{filename}" does not match its declared file type.')

    return extension


def build_attachment_object_key(sanitized_filename: str) -> str:
    now = datetime.now(timezone.utc)
    return f"{now.year:04d}/{now.month:02d}/{uuid.uuid4()}-{sanitized_filename}"
