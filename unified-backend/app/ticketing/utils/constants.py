# constants.py

MAX_ATTACHMENT_FILES = 10
MAX_ATTACHMENT_SIZE_BYTES = 30 * 1024 * 1024  # 30MB

ATTACHMENT_MIME_BY_EXTENSION: dict[str, set[str]] = {
    "pdf": {"application/pdf"},
    "doc": {"application/msword"},
    "docx": {"application/vnd.openxmlformats-officedocument.wordprocessingml.document"},
    "xls": {"application/vnd.ms-excel"},
    "xlsx": {"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"},
    "csv": {"text/csv", "application/csv", "application/vnd.ms-excel"},
    "png": {"image/png"},
    "jpg": {"image/jpeg"},
    "jpeg": {"image/jpeg"},
    "gif": {"image/gif"},
    "txt": {"text/plain"},
    "zip": {"application/zip", "application/x-zip-compressed", "multipart/x-zip"},
    # winmail.dat (TNEF) — preserved as an opaque file, never decoded.
    "dat": {"application/ms-tnef", "application/octet-stream"},
    # A forwarded/nested email ("Attach as email" in Outlook), synthesized
    # by graph_client.py's itemAttachment resolution — see
    # mail_mapping_service.GRAPH_ITEM_ATTACHMENT_ODATA_TYPE.
    "eml": {"message/rfc822"},
}

# Phase 2 hardening: magic-byte/content-sniffing groups for
# validators.validate_attachment_magic_bytes — a second, defense-in-
# depth gate on top of the extension allow-list above (which remains
# the real security gate). Grouped by family, not exact MIME string,
# because .docx/.xlsx are themselves ZIP containers and .doc/.xls are
# themselves OLE compound-file containers — an exact-match check would
# risk false-rejecting a genuine Outlook attachment depending on the
# host's libmagic version/database. Extensions with no reliable fixed
# byte signature (plain text, TNEF) are never sniffed at all.
ATTACHMENT_MAGIC_STRICT_MIME_BY_EXTENSION: dict[str, str] = {
    "pdf": "application/pdf",
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "gif": "image/gif",
}

ATTACHMENT_MAGIC_OLE_EXTENSIONS = frozenset({"doc", "xls"})

ATTACHMENT_MAGIC_ZIP_EXTENSIONS = frozenset({"docx", "xlsx", "zip"})

# No reliable fixed magic signature for these — never sniffed.
ATTACHMENT_MAGIC_SKIP_EXTENSIONS = frozenset({"txt", "csv", "eml", "dat"})
