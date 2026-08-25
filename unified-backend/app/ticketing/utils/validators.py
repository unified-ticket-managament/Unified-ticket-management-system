# validators.py

import logging
import os
import re
import uuid
from datetime import datetime, timezone

from app.ticketing.utils.constants import (
    ATTACHMENT_MAGIC_OLE_EXTENSIONS,
    ATTACHMENT_MAGIC_SKIP_EXTENSIONS,
    ATTACHMENT_MAGIC_STRICT_MIME_BY_EXTENSION,
    ATTACHMENT_MAGIC_ZIP_EXTENSIONS,
    ATTACHMENT_MIME_BY_EXTENSION,
)

logger = logging.getLogger(__name__)

# Logged once per process, not once per upload, so an environment
# with no libmagic installed doesn't spam the log on every request.
_magic_unavailable_warned = False

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


def validate_attachment_magic_bytes(filename: str, extension: str, data: bytes) -> None:
    """
    Phase 2 hardening: a second, content-based gate on top of
    validate_attachment_type's extension allow-list — sniffs the first
    few KB of the actual file bytes and rejects a confirmed mismatch
    (e.g. a renamed .exe saved with a .pdf extension, which the
    extension check alone can't catch since it never inspects content).

    Deliberately family-based, not an exact MIME match, for the
    ambiguous ZIP/OLE-container formats — see
    ATTACHMENT_MAGIC_*_EXTENSIONS's own comments in constants.py for
    why an exact match would risk false-rejecting a genuine Outlook
    attachment. Extensions with no reliable fixed byte signature
    (txt/csv/eml/dat) are never sniffed.

    This is defense-in-depth only, never a replacement for the
    extension allow-list. `python-magic` wraps libmagic, a system C
    library not bundled with Python — any failure to import it or to
    actually sniff (e.g. libmagic isn't installed on this host at all,
    the common case on local Windows dev) is caught, logged once, and
    treated as "skip this check" rather than blocking the upload.
    """

    if extension in ATTACHMENT_MAGIC_SKIP_EXTENSIONS:
        return

    try:
        import magic

        sniffed_mime = magic.from_buffer(data[:4096], mime=True)
    except Exception:
        global _magic_unavailable_warned
        if not _magic_unavailable_warned:
            logger.warning(
                "Magic-byte content sniffing unavailable (libmagic not "
                "installed/loadable) — skipping this check for all "
                "attachment uploads; the extension allow-list remains "
                "the active security gate."
            )
            _magic_unavailable_warned = True
        return

    if extension in ATTACHMENT_MAGIC_STRICT_MIME_BY_EXTENSION:
        expected = ATTACHMENT_MAGIC_STRICT_MIME_BY_EXTENSION[extension]
        if sniffed_mime != expected:
            raise ValueError(
                f'"{filename}" does not look like a real .{extension} file '
                f"(detected content type: {sniffed_mime})."
            )
    elif extension in ATTACHMENT_MAGIC_OLE_EXTENSIONS:
        normalized = sniffed_mime.lower()
        if not (
            normalized.startswith("application/msword")
            or normalized.startswith("application/vnd.ms-excel")
            or "ole" in normalized
            or "cdf" in normalized
        ):
            raise ValueError(
                f'"{filename}" does not look like a real .{extension} file '
                f"(detected content type: {sniffed_mime})."
            )
    elif extension in ATTACHMENT_MAGIC_ZIP_EXTENSIONS:
        if not (
            sniffed_mime.startswith("application/zip")
            or sniffed_mime.startswith("application/x-zip")
            or sniffed_mime.startswith("application/vnd.openxmlformats-officedocument")
        ):
            raise ValueError(
                f'"{filename}" does not look like a real .{extension} file '
                f"(detected content type: {sniffed_mime})."
            )


def build_attachment_object_key(sanitized_filename: str) -> str:
    now = datetime.now(timezone.utc)
    return f"{now.year:04d}/{now.month:02d}/{uuid.uuid4()}-{sanitized_filename}"
