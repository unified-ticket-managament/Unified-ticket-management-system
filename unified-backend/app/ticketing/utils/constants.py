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
    # Phase 3 full-matrix expansion. Macro-enabled Office formats
    # (docm/xlsm/pptm), .msg (Outlook's native binary format, no
    # parser exists), and any executable extension are deliberately
    # NOT added here — they must stay rejected by the allow-list gate.
    "rtf": {"application/rtf", "text/rtf"},
    "odt": {"application/vnd.oasis.opendocument.text"},
    "ods": {"application/vnd.oasis.opendocument.spreadsheet"},
    "ppt": {"application/vnd.ms-powerpoint"},
    "pptx": {"application/vnd.openxmlformats-officedocument.presentationml.presentation"},
    "odp": {"application/vnd.oasis.opendocument.presentation"},
    "bmp": {"image/bmp"},
    "webp": {"image/webp"},
    "tiff": {"image/tiff"},
    "tif": {"image/tiff"},
    "ico": {"image/x-icon", "image/vnd.microsoft.icon"},
    "heic": {"image/heic"},
    "heif": {"image/heif"},
    # SVG can carry embedded script — never eligible for inline/
    # preview rendering, see NEVER_INLINE_EXTENSIONS below. Still
    # safe to store/download like any other file.
    "svg": {"image/svg+xml"},
    "mp4": {"video/mp4"},
    "mov": {"video/quicktime"},
    "avi": {"video/x-msvideo"},
    "wmv": {"video/x-ms-wmv"},
    "mkv": {"video/x-matroska"},
    "mp3": {"audio/mpeg"},
    "wav": {"audio/wav", "audio/x-wav"},
    "m4a": {"audio/mp4", "audio/x-m4a"},
    "aac": {"audio/aac"},
    # Phase 4 gap fix. Common voice-memo/relay container formats that
    # were missing from the original mp3/wav/m4a/aac-only audio set —
    # a legitimate, allow-listed audio attachment in one of these
    # formats was previously rejected the same way a deliberately
    # unsupported type is, but for an unintentional reason.
    "oga": {"audio/ogg"},
    "opus": {"audio/opus", "audio/ogg"},
    "amr": {"audio/amr", "audio/3gpp"},
    "wma": {"audio/x-ms-wma"},
    "3gp": {"audio/3gpp", "video/3gpp"},
    "rar": {"application/vnd.rar", "application/x-rar-compressed"},
    "7z": {"application/x-7z-compressed"},
    "tar": {"application/x-tar"},
    "gz": {"application/gzip", "application/x-gzip"},
    "bz2": {"application/x-bzip2"},
    "py": {"text/x-python", "text/plain"},
    "js": {"text/javascript", "application/javascript"},
    # video/mp2t is the IANA-registered MIME for .ts (MPEG transport
    # stream) — genuinely ambiguous with TypeScript source. Harmless:
    # the content_type check below is advisory-only, never rejects.
    "ts": {"video/mp2t", "text/plain"},
    "java": {"text/x-java-source", "text/plain"},
    "html": {"text/html"},
    "css": {"text/css"},
    "json": {"application/json"},
    "xml": {"application/xml", "text/xml"},
    "sql": {"application/sql", "text/plain"},
    "md": {"text/markdown", "text/plain"},
    "log": {"text/plain"},
}

# Never eligible for inline/preview rendering (a presigned URL with
# Content-Disposition: inline, opened via direct browser navigation
# rather than an <img> tag) even though the extension is otherwise
# allow-listed above — active-content risk. Subtracted out of
# IMAGE_EXTENSIONS below, which is what actually gates preview
# eligibility now.
NEVER_INLINE_EXTENSIONS = frozenset({"svg"})

# Canonical "safe to render inline/preview" extension set, derived
# from the allow-list's own image/* MIME values above and then minus
# NEVER_INLINE_EXTENSIONS. Whether an attachment is eligible for a
# Content-Disposition: inline preview URL must be decided from this
# (the filename extension — the same signal the allow-list/magic-byte
# gates already treat as authoritative), never from the stored
# attachment.mime_type: that value is the client/sender-declared
# Content-Type, never independently verified against the actual bytes
# for most extensions (see ATTACHMENT_MAGIC_SKIP_EXTENSIONS below), so
# trusting it here would let a file named e.g. "payload.txt" with a
# spoofed "image/svg+xml" Content-Type mint a real inline-disposition
# preview URL — a stored-XSS path once that URL is opened via direct
# navigation rather than an <img> tag.
IMAGE_EXTENSIONS = frozenset(
    extension
    for extension, mimes in ATTACHMENT_MIME_BY_EXTENSION.items()
    if any(mime.startswith("image/") for mime in mimes)
    ) - NEVER_INLINE_EXTENSIONS

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

ATTACHMENT_MAGIC_OLE_EXTENSIONS = frozenset({"doc", "xls", "ppt"})

ATTACHMENT_MAGIC_ZIP_EXTENSIONS = frozenset({"docx", "xlsx", "zip", "pptx", "odt", "ods", "odp"})

# No reliable fixed magic signature for these — never sniffed.
ATTACHMENT_MAGIC_SKIP_EXTENSIONS = frozenset({
    "txt", "csv", "eml", "dat",
    "rtf",
    "bmp", "webp", "tiff", "tif", "ico", "heic", "heif", "svg",
    "mp4", "mov", "avi", "wmv", "mkv",
    "mp3", "wav", "m4a", "aac", "oga", "opus", "amr", "wma", "3gp",
    "rar", "7z", "tar", "gz", "bz2",
    "py", "js", "ts", "java", "html", "css", "json", "xml", "sql", "md", "log",
})
