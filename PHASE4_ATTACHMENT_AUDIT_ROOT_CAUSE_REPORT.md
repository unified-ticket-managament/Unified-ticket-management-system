# Phase 4 — Inbound Attachment Compatibility Audit: Root-Cause Report

**Status: INVESTIGATION ONLY. No code has been modified.** This report is the
required deliverable before any implementation work begins. All file:line
citations were verified by direct reading of the current working tree
(including uncommitted Phase 3/4 changes) on 2026-08-25.

**Live Graph verification was not available in this session.** Every finding
below is code-traced against `unified-backend/app/ticketing/` and its test
suite. Anywhere this report says "NOT LIVE VERIFIED", that specific claim is
unconfirmed against a real Outlook/Graph mailbox — treat the code trace as
strong evidence of what *would* happen, not proof of what a real mailbox
*does* send.

---

## A. Executive summary

The reported symptom — **email body arrives intact, but a visible-in-Outlook
attachment (reproduced with audio) never appears in UTMS** — is explained by
**three independent, code-confirmed root causes**, all inside
`unified-backend/app/ticketing/services/mail_mapping_service.py` and
`graph_client.py`. They are not mutually exclusive; any one of them alone
reproduces the symptom, and it is not possible from static code reading alone
to say which one actually fired for the specific reproduction case. Section G
gives a diagnostic step to disambiguate before any fix is written.

None of the three are frontend bugs. The frontend was independently traced
and found to have **no** extension/MIME allow-list, denylist, or
preview-required gate in the received-message rendering path — every
attachment type (audio, video, archive, code/text) renders identically to a
PDF (generic icon + filename + size + Download link) once the backend
actually returns it. The single frontend risk found (trusting a
backend-supplied `is_inline` boolean with no fallback rendering for inline
items) is currently *not* exploitable given the backend's current
`is_inline` assignment logic (Section B, RC2) — it only ever marks a
non-image attachment `is_inline` under a bug scenario already covered by
RC2's own analysis, so it is not a fourth independent cause, just a
downstream amplifier if RC2's guard were ever loosened incorrectly.

The security boundary (allow-list, magic-byte validation, macro/`.msg`/`.exe`
rejection) is intact and is **not** implicated in the audio-drop symptom.

---

## B. Root causes

### RC1 — Whole-message attachment loss on one malformed Graph attachment item (structural, not type-specific)

**File:** `unified-backend/app/ticketing/services/graph_client.py:941`

```python
return [GraphAttachmentPayload.model_validate(item) for item in raw_items]
```

`GraphAttachmentPayload.name` (`unified-backend/app/ticketing/schemas/mail_integration.py:140`) is typed `str = Field(default="attachment")` — **not** `str | None`. The default only covers a missing key; if Graph (or a relay/forwarder in the chain) returns `"name": null` explicitly for even one attachment on a message, Pydantic v2 raises `ValidationError` for that single dict, and because this is a bare list comprehension with **no per-item `try/except`**, the exception kills the entire method call — every attachment on that message is lost, not just the malformed one.

This is the exact bug shape that `list_new_messages` (same file, lines 850-885) was *already fixed for* in the current diff — a per-item `try/except ValidationError` that logs and skips one poison item — but `fetch_message_attachments` never received the equivalent fix.

The exception propagates uncaught out of `fetch_message_attachments`, straight into the caller's blanket handler:

- `unified-backend/app/ticketing/api/mail_integration.py:244-255` (webhook path)
- `unified-backend/app/ticketing/services/graph_mail_poller.py:281-293` (polling path, byte-identical pattern)

```python
files = None
if payload.id and (...):
    try:
        attachments = await mail_provider_client.fetch_message_attachments(payload.id)
        files = build_upload_files_from_graph_attachments(attachments, payload.body.content)
    except Exception:
        logger.exception("... storing without them", ...)
```

Both transports catch *any* exception from the fetch+map step and fall through with `files = None`. `EmailService.receive_email` then proceeds to create the Interaction with the body intact and **zero attachments** — an exact match for "body intact, attachment missing." This is **message-scoped**: if the message has one attachment (the audio file) and it happens to trip this, the whole attachment set vanishes; if there were other attachments too, they would vanish as collateral damage, indistinguishable from the reported single-attachment case.

**Type-specificity:** none. Any extension can trigger this if the specific Graph attachment item has a null/malformed field. Not audio-specific by mechanism, but audio/voice attachments from non-Outlook-native relays (voicemail systems, mobile clients) are a plausible source of an unusual attachment shape Graph hasn't been tested against.

### RC2 — Non-image attachments reported `isInline: true` by Graph are unconditionally dropped (type-differentiated, most likely candidate for audio specifically)

**File:** `unified-backend/app/ticketing/services/mail_mapping_service.py:419-439`

```python
is_inline_image = bool(
    attachment.contentId
    and (attachment.isInline or is_referenced_in_body)
    and (attachment.contentType or "").startswith("image/")
)

if attachment.isInline and not is_inline_image:
    logger.warning(
        "Dropping Graph attachment %r — inline attachment with no "
        "resolvable contentId, or not an image",
        display_name,
    )
    dropped += 1
    continue
```

Any Graph attachment reported with `isInline: true` whose `contentType` does not start with `image/` is unconditionally, silently dropped — logged only, `continue`d past, no exception, no recovery. This is deliberate, documented, and tested behavior for the *general* case (the function's own docstring, lines 350-364, explains the intent: an inline non-image attachment has no `cid:` reference an HTML body could ever resolve, so there's "no reason to store it"). It is explicitly covered by `unified-backend/tests/test_graph_mail_integration.py`'s `test_build_upload_files_from_graph_attachments_drops_inline_attachments` — but that test's fixture is a **PDF**, and no test in the suite exercises this branch for audio, video, or any other non-image, non-PDF type.

The premise behind "no reason to store it" — that an `isInline` attachment is always referenceable from body HTML via `cid:` — holds for genuine inline images (signatures, pasted screenshots) but **does not hold for audio**. The code's own comment elsewhere in the same file (`mail_mapping_service.py:389-393`) states Graph's `isInline` "is itself only a heuristic derived from the original MIME `Content-Disposition` header and is not reliable across every sending client/relay." Voicemail/relay systems and some mobile mail clients are known to set `Content-Disposition: inline` on audio attachments (so a mail client that embeds an audio player can identify them), with no corresponding `cid:` reference in the body at all — Outlook then surfaces this to Graph as `isInline: true`, `contentType: audio/mpeg` (or similar), and the current logic drops it as if it were an orphaned inline image.

**Type-specificity:** high. This branch treats "not an image" as sufficient grounds to drop, with no allowance for a non-image type that is genuinely `isInline` from the sender's perspective but still meant to be a real, downloadable attachment. This is the most likely explanation for why **audio specifically** reproduces the bug while PDF/DOCX/image attachments from normal desktop Outlook compose (which essentially never set `isInline: true`) do not.

**Not yet confirmed live**: whether the actual reproduction's audio attachment really arrives from Graph with `isInline: true`. See Section G for the diagnostic to confirm this before treating it as *the* fix target.

### RC3 — A magic-byte mismatch on a ZIP/OLE-family extension aborts the *entire* email, not just that attachment (distinct failure mode, not what was reproduced, but a real bug worth flagging)

**File:** `unified-backend/app/ticketing/services/attachment_service.py:333-405` (`validate_and_store_files`), consumed by `unified-backend/app/ticketing/services/email_service.py:620` (`receive_email`)

`validate_and_store_files` is a plain `for` loop with no per-file exception boundary. `validate_attachment_type` and `validate_attachment_magic_bytes` both `raise HTTPException` on failure (lines 350, 369). Since `build_upload_files_from_graph_attachments` (Stage covering RC2) only pre-checks extension/size/base64-decodability — **it does not pre-check magic bytes** — a genuine magic-byte mismatch for any of the extensions actually sniffed (`pdf, png, jpg, jpeg, gif` — exact match; `doc, xls, ppt` — OLE family; `docx, xlsx, zip, pptx, odt, ods, odp` — ZIP family) raises `HTTPException` here, uncaught by anything between this call and `receive_email`'s own caller. It propagates out to the transport-level `except Exception` in `mail_integration.py`/`graph_mail_poller.py`, which **rolls back the whole DB transaction** — the entire Interaction, including the message body and every other valid attachment in the same email — and records an `inbound_mail_failures` row for retry.

This does **not** match "body intact, attachment missing" (the symptom here is "whole email missing/retried"), so it is very unlikely to be the cause of the reported bug specifically, but it is a real, distinct defect: one bad-typed attachment (e.g. a renamed/corrupted ZIP-family file, or a false-positive libmagic mismatch depending on host libmagic version — see `validators.py:94-108`) can take down an otherwise-good email that has several other valid attachments alongside it. Audio extensions are all in `ATTACHMENT_MAGIC_SKIP_EXTENSIONS` and cannot trigger this path, so RC3 is ruled out for the specific audio reproduction, but is included here because the audit was scoped to *all* attachment types, not just audio.

### RC4 — Allow-list gap for common voice-memo container formats (format-specific, security-neutral)

**File:** `unified-backend/app/ticketing/utils/constants.py:6-74` (`ATTACHMENT_MIME_BY_EXTENSION`)

`mp3, wav, m4a, aac` are all present in the allow-list. However, several other real-world voice/audio container formats are **not**: `.oga` (Ogg audio), `.opus`, `.amr` (a very common format for voice memos recorded on Android/some VoIP/relay systems), `.wma`, `.3gp`/`.3gpp` (older mobile voice-memo containers). Any attachment with one of these extensions — or with no extension at all, since `GraphAttachmentPayload.name` defaults to the literal string `"attachment"` when Graph omits `name` — is rejected by `validate_attachment_type` at `mail_mapping_service.py:481-488` and silently dropped (logged, `continue`d), the same as the intentionally-rejected `.docm`/`.msg`/`.exe` types, but for an unintentional reason: these are legitimate audio formats simply missing from the matrix, not a deliberate security exclusion.

**This is a real possibility for the reported bug** if the actual failing attachment's true extension (as sent by the originating device, before any relay renames it) is one of these rather than `.mp3`/`.wav`/`.m4a`/`.aac`. This must be checked against the actual reproduction before assuming RC2 is the cause instead.

### Frontend (traced, not an independent root cause given current backend behavior)

**File:** `unified-frontend/src/ticket-workspace/components/common/AttachmentList.tsx:14`, `unified-frontend/src/ticket-workspace/components/mail/MessageDetailsView.tsx:287`

Both components filter the attachment list on `!attachment.is_inline` before rendering, and neither has any fallback rendering for an item where `is_inline: true`. This is safe **only because** the backend's current `is_inline_image` computation (RC2's own `is_inline_image` boolean) guarantees `is_inline=True` is only ever persisted for attachments whose `contentType` starts with `image/` — i.e., today, a non-image attachment can never reach the frontend already marked inline. If a future backend change ever widened what qualifies as `is_inline` (e.g. attempting a naive fix to RC2 that flips `isInline` through without also gating on `contentType`), that widened set would vanish from these two frontend views with zero trace, since there is no generic "downloadable inline-marked item" fallback anywhere in the receive-side renderers. This is a **latent defense-in-depth gap**, not a currently-triggered bug — flagged so any fix to RC2 does not introduce it. `TicketAttachmentsTab.tsx` does not filter by `is_inline` at all, so it would remain a diagnostic differential (present there, absent from Mail thread view) if this gap were ever hit.

---

## C. Complete compatibility matrix

Columns: **Allowed** = extension present in `ATTACHMENT_MIME_BY_EXTENSION`. **Magic-byte** = which validation family, or `skip` (no sniffing at all). **Status** reflects the pipeline trace, not a live test, unless marked. **Root cause** references the sections above; "—" means no known drop risk beyond the two universal, type-neutral gates (RC1, and the >10-file / >30MB caps, which apply identically to every type and are not repeated per row).

| Extension | Category | Allowed | Expected MIME (constants.py) | Magic-byte family | Status | Root cause |
|---|---|---|---|---|---|---|
| pdf | Document | Yes | application/pdf | strict | SUPPORTED (code-traced; NOT LIVE VERIFIED) | RC1 (rare), RC3 if magic mismatch |
| doc | Document | Yes | application/msword | OLE | SUPPORTED (code-traced) | RC1 (rare), RC3 |
| docx | Document | Yes | vnd...wordprocessingml.document | ZIP | SUPPORTED (code-traced) | RC1 (rare), RC3 |
| txt | Document | Yes | text/plain | skip | SUPPORTED (code-traced) | RC1 (rare) |
| rtf | Document | Yes | application/rtf, text/rtf | skip | SUPPORTED (code-traced) | RC1 (rare) |
| odt | Document | Yes | vnd.oasis.opendocument.text | ZIP | SUPPORTED (code-traced) | RC1, RC3 |
| xls | Spreadsheet | Yes | application/vnd.ms-excel | OLE | SUPPORTED (code-traced) | RC1, RC3 |
| xlsx | Spreadsheet | Yes | vnd...spreadsheetml.sheet | ZIP | SUPPORTED (code-traced) | RC1, RC3 |
| csv | Spreadsheet | Yes | text/csv, application/csv, vnd.ms-excel | skip | SUPPORTED (code-traced) | RC1 (rare) |
| ods | Spreadsheet | Yes | vnd.oasis.opendocument.spreadsheet | ZIP | SUPPORTED (code-traced) | RC1, RC3 |
| ppt | Presentation | Yes | application/vnd.ms-powerpoint | OLE | SUPPORTED (code-traced) | RC1, RC3 |
| pptx | Presentation | Yes | vnd...presentationml.presentation | ZIP | SUPPORTED (code-traced) | RC1, RC3 |
| odp | Presentation | Yes | vnd.oasis.opendocument.presentation | ZIP | SUPPORTED (code-traced) | RC1, RC3 |
| jpg/jpeg | Image | Yes | image/jpeg | strict | SUPPORTED (code-traced) | RC1 (rare) |
| png | Image | Yes | image/png | strict | SUPPORTED (code-traced) | RC1 (rare) |
| gif | Image | Yes | image/gif | strict | SUPPORTED (code-traced) | RC1 (rare) |
| bmp | Image | Yes | image/bmp | skip | SUPPORTED (code-traced) | RC1 (rare) |
| webp | Image | Yes | image/webp | skip | SUPPORTED (code-traced); browser `<img>` support NOT LIVE VERIFIED | RC1 (rare) |
| tiff/tif | Image | Yes | image/tiff | skip | PARTIALLY SUPPORTED — pipeline stores it, but most browsers cannot render TIFF in an `<img>` tag; would show a broken-thumbnail icon in `AttachmentList.tsx`'s image branch. NOT LIVE VERIFIED | Frontend rendering gap (not a drop — file is still downloadable) |
| ico | Image | Yes | image/x-icon | skip | SUPPORTED, low real-world relevance as an email attachment | — |
| heic/heif | Image | Yes | image/heic, image/heif | skip | PARTIALLY SUPPORTED — same as TIFF: stored/downloadable, but most desktop browsers cannot decode HEIC in `<img>`; iPhone-originated photos are the primary real-world case. NOT LIVE VERIFIED | Frontend rendering gap (not a drop) |
| svg | Image | Yes | image/svg+xml | skip | SUPPORTED as a normal (non-inline-eligible) download per `NEVER_INLINE_EXTENSIONS`; **edge case**: if Graph ever reports a genuine `isInline: true` SVG referenced via `cid:` in the body, backend's `is_inline_image` check does not special-case SVG out (only the frontend's separate `NEVER_INLINE_EXTENSIONS` list does), so it could be persisted `is_inline=True` and excluded from the normal attachment list. NOT LIVE VERIFIED, likely rare | Edge case worth a dedicated live test, not a confirmed bug |
| mp4 | Video | Yes | video/mp4 | skip | SUPPORTED, but shares RC2's exposure if a client/relay marks it `isInline: true` | RC1, **RC2 (theoretical)** |
| mov | Video | Yes | video/quicktime | skip | SUPPORTED (code-traced) | RC1, **RC2 (theoretical)** |
| avi | Video | Yes | video/x-msvideo | skip | SUPPORTED (code-traced) | RC1, **RC2 (theoretical)** |
| wmv | Video | Yes | video/x-ms-wmv | skip | SUPPORTED (code-traced) | RC1, **RC2 (theoretical)** |
| mkv | Video | Yes | video/x-matroska | skip | SUPPORTED (code-traced) | RC1, **RC2 (theoretical)** |
| mp3 | Audio | Yes | audio/mpeg | skip | **PARTIALLY SUPPORTED / SILENTLY DROPPED** when Graph reports `isInline: true` | **RC2 (primary suspect)**, RC1 |
| wav | Audio | Yes | audio/wav, audio/x-wav | skip | **PARTIALLY SUPPORTED / SILENTLY DROPPED** when `isInline: true` | **RC2**, RC1 |
| m4a | Audio | Yes | audio/mp4, audio/x-m4a | skip | **PARTIALLY SUPPORTED / SILENTLY DROPPED** when `isInline: true` | **RC2**, RC1 |
| aac | Audio | Yes | audio/aac | skip | **PARTIALLY SUPPORTED / SILENTLY DROPPED** when `isInline: true` | **RC2**, RC1 |
| oga / opus / amr / wma / 3gp | Audio | **No** | n/a | n/a | **REJECTED** (allow-list gap, not intentional security exclusion) | **RC4** |
| zip | Archive | Yes | application/zip, x-zip-compressed, multipart/x-zip | ZIP | SUPPORTED (code-traced; regression-tested per Phase 3 checklist) | RC1, RC3 |
| rar | Archive | Yes | vnd.rar, x-rar-compressed | skip | SUPPORTED (code-traced) | RC1 |
| 7z | Archive | Yes | x-7z-compressed | skip | SUPPORTED (code-traced) | RC1 |
| tar | Archive | Yes | x-tar | skip | SUPPORTED (code-traced) | RC1 |
| gz | Archive | Yes | gzip, x-gzip | skip | SUPPORTED for a bare `.gz`; a compound `archive.tar.gz` resolves to extension `gz` only (last-suffix extraction) — treated/iconified as gzip, not tar, cosmetic only, not a drop | RC1; nested-extension cosmetic mislabel |
| bz2 | Archive | Yes | x-bzip2 | skip | SUPPORTED (code-traced) | RC1 |
| py/js/ts/java/html/css/json/xml/sql/md/log | Code/Text | Yes | see constants.py (all advisory-only MIME sets) | skip | SUPPORTED (code-traced) — MIME mismatch from Graph never rejects, only logs | RC1 |
| dat (TNEF/winmail.dat) | Other | Yes | application/ms-tnef, application/octet-stream | skip | SUPPORTED as an opaque, non-decoded file — documented limitation (rich TNEF content not extracted), not a bug | RC1 |
| eml (forwarded/"Attach as email") | Other | Yes | message/rfc822 | skip | SUPPORTED via `itemAttachment` → synthetic `fileAttachment` resolution (`graph_client.py`'s `_resolve_item_attachments`). NOT LIVE VERIFIED (present on the still-unchecked Phase 3 manual checklist) | RC1 |
| docm / xlsm / pptm | Macro-enabled Office | **No** | n/a | n/a | **INTENTIONALLY REJECTED** — security boundary, by design | Security (Section F) |
| msg | Outlook native binary | **No** | n/a | n/a | **INTENTIONALLY REJECTED** — no parser exists, by design | Security (Section F) |
| exe / any executable | Executable | **No** | n/a | n/a | **INTENTIONALLY REJECTED** | Security (Section F) |
| referenceAttachment (generic, non-cloud-link) | Graph type | N/A — odata.type based, not extension | n/a | n/a | **SILENTLY DROPPED**, logged as "not a file attachment" at `mail_mapping_service.py:455-466`, regardless of the underlying file's extension | Deliberate — see Section E |

---

## D. Failure points — exactly where each failing format disappears

- **Any type, message-level (RC1):** disappears at `graph_client.py:941` (uncaught `ValidationError` on one malformed item) → caught by the blanket `except Exception` at `mail_integration.py:251` / `graph_mail_poller.py:288` → `files=None` passed into `EmailService.receive_email` → email is created with body only, zero attachments, no per-attachment trace anywhere.
- **Audio/video/any non-image marked `isInline` by Graph (RC2):** disappears at `mail_mapping_service.py:432-439`, one `logger.warning` line ("Dropping Graph attachment ... inline attachment with no resolvable contentId, or not an image") is the only trace. Never reaches `AttachmentService.validate_and_store_files`, never reaches the DB, never reaches the API or frontend.
- **ZIP/OLE-family magic-byte mismatch (RC3):** disappears at `attachment_service.py`'s `validate_and_store_files` (raises `HTTPException`) → uncaught until the transport-level handler → **whole email transaction rolled back**, retried, not just the one attachment.
- **Unlisted voice/audio formats, or a nameless attachment (RC4):** disappears at `mail_mapping_service.py:481-488` (`validate_attachment_type` raises `ValueError`, caught locally, logged, `continue`d) — same mechanism as the intentional `.docm`/`.msg`/`.exe` rejections, just for an unintentional reason.
- **referenceAttachment / non-fileAttachment odata types other than a resolved itemAttachment:** disappears at `mail_mapping_service.py:455-466`, logged as "not a file attachment."

---

## E. Outlook/Graph behavior

Only two of the three polymorphic Graph attachment types are meaningfully handled by this codebase today:

1. **`fileAttachment`** (`#microsoft.graph.fileAttachment`) — the normal case for a real file (any of the extensions in the matrix above). Carries `contentBytes` (base64), `contentType`, `size`, `name`, `isInline`, `contentId`. This is the only type `build_upload_files_from_graph_attachments` accepts without special resolution.
2. **`itemAttachment`** (`#microsoft.graph.itemAttachment`) — used for "Attach as email"/forwarded-message attachments. Graph's `/attachments` list endpoint never returns `contentBytes` for this odata type directly; `graph_client.py`'s `_resolve_item_attachments` does a second, item-scoped fetch (with its own local `try/except`, correctly isolated per item) to resolve it into a synthetic `message/rfc822` `fileAttachment`-shaped object before the mapping function sees it.
3. **`referenceAttachment`** — used for genuine reference-style share links (distinct from the OneDrive/SharePoint HTML-anchor cloud-link mechanism documented in CLAUDE.md, which produces `hasAttachments: False` and an **empty** attachments collection — that mechanism never surfaces a `referenceAttachment` object at all in the confirmed-live case). This codebase has **no explicit handling** for a genuine `referenceAttachment` object appearing in the `/attachments` collection — it falls through to the generic "`@odata.type` present and not fileAttachment" rejection at `mail_mapping_service.py:455-466` and is dropped, logged only. Whether Outlook/Graph actually produces a real `referenceAttachment` object in any scenario distinct from the already-handled cloud-link-via-body-anchor case is **NOT LIVE VERIFIED** — no test in the suite constructs one, and no live Graph payload was available this session.

`@odata.type` is only reliably present because `fetch_message_attachments` deliberately omits `$select` (confirmed fixed per the documented historical bug — see CLAUDE.md's "Inbound Graph attachments" section and `graph_client.py:901-911`'s docstring). A `None` `@odata.type` is explicitly tolerated, not treated as disqualifying (`mail_mapping_service.py:455-457`).

No live Graph capture of real request/response payloads for any category was performed this session (no credentials available in this investigation context) — all Graph-shape claims above are derived from code comments, docstrings, and existing test fixtures, which is a reliable but secondary source next to a live capture.

---

## F. Security analysis

Confirmed intact, not implicated in the reported bug:

- **`.docm`/`.xlsm`/`.pptm`** (macro-enabled Office) — absent from `ATTACHMENT_MIME_BY_EXTENSION` by explicit design (`constants.py:25-28` comment). Rejected at the allow-list gate, same mechanism as any other unlisted extension.
- **`.msg`** — Outlook's native binary format; absent because "no parser exists," not purely a security call, but has the same rejection effect.
- **Executables** (`.exe` and any other unlisted extension) — rejected at the same allow-list gate.
- **Magic-byte validation** (`validators.py`) remains a defense-in-depth layer on top of the allow-list for the subset of extensions with a reliable fixed byte signature (`pdf/png/jpg/jpeg/gif` exact; `doc/xls/ppt` OLE; `docx/xlsx/zip/pptx/odt/ods/odp` ZIP-family) — untouched by any of RC1/RC2/RC4, and RC3 (Section B) shows it currently fails *closed* in a way that's arguably too aggressive (kills the whole email) rather than too permissive — not a security weakening.
- **SVG** — deliberately excluded from inline/preview rendering via `NEVER_INLINE_EXTENSIONS` to prevent a stored-XSS path through a `Content-Disposition: inline` preview URL opened via direct navigation; still safely downloadable like any other file. The Section C edge case (an SVG genuinely `isInline` + `cid:`-referenced) does not bypass this — it would only ever render inside an `<img>` tag context (which cannot execute embedded script), never as a direct-navigation preview URL; flagged for a live test, not a suspected vulnerability.
- **No recommendation in this report proposes loosening the allow-list, disabling magic-byte validation, treating `application/octet-stream` as universally safe, or reversing any of the docm/msg/exe rejections.**

---

## G. Recommended implementation plan (minimal, safe — NOT YET APPROVED, NOT YET IMPLEMENTED)

**Step 0 — Diagnose before fixing.** Three plausible, independently-sufficient root causes (RC1, RC2, RC4) were found for the audio symptom alone. Before writing any fix, pull one of the following for the actual failing email:
   - Application logs around the message's receipt time, filtered for `"Graph poll: failed to fetch attachments"` / `"Failed to fetch attachments for Graph message"` (→ points to RC1) vs. `"Dropping Graph attachment ... inline attachment with no resolvable contentId, or not an image"` (→ points to RC2) vs. `"Dropping Graph attachment ... "` with a `ValueError` about unsupported extension (→ points to RC4).
   - Or, if logs have rotated out, a live capture of `GET /users/{mailbox}/messages/{id}/attachments` for a reproduction email (needs Graph credentials/live access not available this session) to see the real `isInline`, `contentType`, and `name` values Graph sent for the missing attachment.

**If RC2 is confirmed** (likely, given it's the only type-differentiated cause matching "audio specifically fails, PDF/DOCX don't"):
   - Narrow the drop condition at `mail_mapping_service.py:432` so a non-image `isInline` attachment is only dropped when it's **also** unreferenced by the body (i.e., genuinely orphaned) — mirroring the existing `is_referenced_in_body` signal already computed for images, rather than an unconditional "not an image ⇒ drop." A non-image `isInline` attachment with no possible `cid:` use should still be **stored as a normal, non-inline, downloadable attachment** (the same outcome as if `isInline` had been `False`), not discarded — since there is no body reference to resolve, keeping it as a regular attachment costs nothing and matches user expectation ("Outlook shows it, so it should show here too").

**If RC1 is confirmed or suspected:**
   - Apply the same per-item `try/except ValidationError` pattern already used in `list_new_messages` (`graph_client.py:850-885`) to `fetch_message_attachments`'s list comprehension at line 941, so one malformed attachment is skipped-and-logged rather than failing the whole message's attachment fetch.

**If RC4 is confirmed:**
   - Add the missing common voice-memo extensions (`oga`, `opus`, `amr`, `wma`, `3gp`) to `ATTACHMENT_MIME_BY_EXTENSION` in `constants.py`, alongside their appropriate MIME sets, and to `ATTACHMENT_MAGIC_SKIP_EXTENSIONS` (no reliable universal magic signature for several of these). This is a pure allow-list addition, not a security loosening — same category as the existing mp3/wav/m4a/aac entries.

**Independently, regardless of which RC caused this specific reproduction — worth fixing for completeness of the audit (RC3):**
   - Isolate `validate_and_store_files`'s per-file loop so a single file's `HTTPException` (extension or magic-byte failure) is caught, logged, and excluded from the batch rather than aborting the whole email transaction — bringing it in line with `build_upload_files_from_graph_attachments`'s own already-documented "partial success over whole-email-loss" design philosophy (its docstring at `mail_mapping_service.py:402-409` explicitly states this tradeoff was chosen for exactly this reason).

**Explicitly out of scope for this plan, per your instructions:** touching the allow-list beyond RC4's narrow voice-format addition, touching magic-byte validation logic itself, touching frontend rendering, or adding `.eml`/`.msg`/macro/executable support.

---

## H. Files/functions to modify (once approved)

| File | Function | Change (per Section G) |
|---|---|---|
| `unified-backend/app/ticketing/services/mail_mapping_service.py` | `build_upload_files_from_graph_attachments` (lines 419-439) | RC2 fix — narrow the `isInline`-non-image drop condition |
| `unified-backend/app/ticketing/services/graph_client.py` | `fetch_message_attachments` (line 941) | RC1 fix — per-item validation try/except, mirroring `list_new_messages` |
| `unified-backend/app/ticketing/utils/constants.py` | `ATTACHMENT_MIME_BY_EXTENSION`, `ATTACHMENT_MAGIC_SKIP_EXTENSIONS` | RC4 fix — add missing voice-memo extensions |
| `unified-backend/app/ticketing/services/attachment_service.py` | `validate_and_store_files` (lines 333-405) | RC3 fix — per-file exception isolation |

No frontend files require changes under this plan — the frontend trace found no filtering bug given current backend `is_inline` semantics.

---

## I. Test plan (once approved)

**Unit (mocked Graph, no network):**
- `mail_mapping_service.py`: a non-image, non-referenced `isInline: true` attachment (audio fixture) is now stored as a normal attachment, not dropped — currently only the "still dropped" PDF case is covered; add the "now kept" case explicitly and keep the "still dropped when also unreferenced and non-image" case as regression coverage for the narrowed condition.
- `graph_client.py`: `fetch_message_attachments` with one malformed item (`name: null`) among several well-formed ones returns the well-formed items, not an empty/exception result — mirrors the existing `test_graph_list_new_messages_resilience.py` pattern for `list_new_messages`.
- `constants.py`/`validators.py`: each newly-added voice extension round-trips through `validate_attachment_type` and is correctly placed in the skip-magic set.
- `attachment_service.py`: a batch of N files where one fails validation/magic-bytes results in N-1 stored files and one logged failure, not a full-batch exception.

**Integration:**
- Full `EmailService.receive_email` call with a Graph-shaped payload containing one `isInline: true` audio attachment and one normal PDF attachment — assert both are persisted, correctly flagged (`is_inline=False` for the audio one), and returned by the interaction's attachment list.
- Same with one malformed attachment item alongside a good one, asserting the good one survives.

**Real Outlook (see Section K for the full checklist)** — required to actually close this out, since every one of RC1/RC2/RC3/RC4's real-world trigger conditions (a relay setting `isInline`, Graph's actual field shapes for various client-originated audio) can only be confirmed against a live mailbox.

---

## J. Regression risks

- **RC2 fix**: broadening what counts as a "keep as normal attachment" case must not accidentally start keeping genuinely-orphaned inline signature/logo remnants as visible download-list clutter in the common case (every Outlook signature image, which is legitimately `isInline` + image + referenced) — the fix must preserve the existing `is_referenced_in_body`/`contentId` image-handling path untouched and only add a new "non-image ⇒ becomes a normal attachment" branch, not alter the image branch at all.
- **RC1 fix**: mirroring the `list_new_messages` per-item pattern is low-risk since it's copying an already-shipped, already-tested approach — but must preserve the existing `_resolve_item_attachments` per-item error handling for `itemAttachment` resolution untouched (different code path, already correctly isolated).
- **RC4 fix**: pure allow-list addition — the only regression risk is if any of the newly-added extensions collides with an existing MIME string already used for content-type-based logic elsewhere (grep for each new MIME string across the codebase before adding, not just `constants.py`).
- **RC3 fix**: changing `validate_and_store_files` from all-or-nothing to per-file isolation changes the contract of the function for its *other* callers too (ticket manual upload, not just Graph-sourced mail) — the ticket-upload API path may currently rely on an `HTTPException` surfacing synchronously to give the uploading user immediate feedback ("this file was rejected"); switching to silent partial-success there could regress that UX. This needs explicit design attention, not just a copy-paste of the Graph-side philosophy, since a live human uploader (unlike an automated mail poller) has an active connection to receive an error to.

---

## K. Manual Outlook verification checklist (Phase 4 addendum)

The existing `PHASE3_MANUAL_OUTLOOK_TEST_CHECKLIST.md` already covers the general attachment-type matrix (Section 1) and should be run as-is for baseline coverage. Add the following Phase-4-specific rows, since none of the existing checklist items isolate the `isInline` behavior that RC2 targets:

- [ ] Send a **voice memo recorded and sent directly from Outlook Mobile** (iOS/Android) as an attachment to the app's mailbox — capture whether it arrives in UTMS at all. This is the closest to the original real-world reproduction.
- [ ] Send an `.mp3`/`.wav`/`.m4a`/`.aac` file attached via **desktop Outlook's normal "Attach File"** flow (not recorded in-app) — confirm this control case DOES arrive (if it also fails, RC2's "relay sets isInline" theory is wrong and RC1/RC4 become more likely).
- [ ] If any tool is available to inspect the raw MIME (`Content-Disposition` header) of the specific reproduction email as it left the origin, capture it — confirms/refutes whether the original sender's client actually marked the audio part `inline`.
- [ ] Send a `.mp4` (video) attachment recorded/sent from a mobile device the same way as the voice memo — check whether video shares the same drop behavior (would confirm RC2 is not audio-specific, just triggered more often by audio-originating clients).
- [ ] Attach a `.oga`, `.opus`, `.amr`, or `.wma` file (whichever is realistically available) — confirm it's rejected (expected today, per RC4) and capture the exact filename/extension the app's own error/log shows, to confirm the allow-list gap theory.
- [ ] Forward an "Attach as email" message (`.eml` scenario) — confirm arrival (previously unchecked on the Phase 3 list).
- [ ] If a OneDrive/SharePoint "Share as link" attachment can be sent in a way that produces a genuine `referenceAttachment` Graph object (distinct from the already-confirmed HTML-anchor cloud-link case) — confirm current behavior (expected: dropped, logged, per Section E).
- [ ] Cross-check application logs for every row above against the three log signatures listed in Section G Step 0, to attribute each result to a specific root cause rather than guessing from behavior alone.

---

---

## L. Implementation log (2026-08-25 — approved and applied)

All four root causes were fixed per the minimal plan in Section G:

| RC | File | Change |
|---|---|---|
| RC2 (primary audio-drop cause) | `mail_mapping_service.py` (`build_upload_files_from_graph_attachments`) | A non-image `isInline` attachment (audio/video/etc.) is no longer dropped — it's stored as a normal, non-inline, downloadable attachment. Only a genuinely orphaned inline *image* (no `contentId`, unresolvable) is still dropped. |
| RC1 | `graph_client.py` (`fetch_message_attachments`) | Per-item `try/except ValidationError` around `GraphAttachmentPayload.model_validate`, mirroring the existing fix in `list_new_messages` — one malformed attachment no longer kills every attachment on the message. |
| RC4 | `constants.py` | Added `oga`, `opus`, `amr`, `wma`, `3gp` to `ATTACHMENT_MIME_BY_EXTENSION` and `ATTACHMENT_MAGIC_SKIP_EXTENSIONS`. |
| RC3 | `attachment_service.py` (`validate_and_store_files`) + `email_service.py` (`receive_email`) | Added an opt-in `tolerate_failures` flag — a per-file validation/magic-byte failure is logged and skipped instead of aborting the whole batch. Wired to `True` only at the inbound-email call site (`email_service.py:620`); every other caller (ticket upload, reply/internal-note attachments in `interaction_service.py`) is untouched and keeps its existing fail-fast `HTTPException` behavior, since those are interactive requests with a human waiting for synchronous feedback. |

**Frontend:** no changes — the audit found no frontend filtering bug given the backend's (now-fixed) `is_inline` semantics.

**Tests:**
- `mail_mapping_service.py`'s outdated test (`test_build_upload_files_from_graph_attachments_drops_inline_attachments`, which asserted the *old* drop-everything-inline behavior) was rewritten as `test_build_upload_files_from_graph_attachments_keeps_non_image_inline_attachment`, plus a new direct regression test `test_build_upload_files_from_graph_attachments_keeps_inline_audio` reproducing the exact reported scenario (an `isInline`-flagged `.mp3` with no `contentId`).
- `tests/test_graph_mail_integration.py` (82 tests): all pass except one pre-existing, unrelated failure (`test_map_external_email_to_interaction_landed_mailbox_none_by_default` — an HTML-table assertion, confirmed failing identically on a clean `git stash`ed tree before any Phase 4 change; not touched by this work).
- `tests/test_graph_list_new_messages_resilience.py`, `tests/test_graph_client_retry_and_attachments.py`, `tests/test_attachment_allowlist_expansion.py`: all pass unmodified.
- All four edited files pass an `ast.parse` syntax check.
- **Environment limitation surfaced during verification (pre-existing, unrelated to this fix):** `tests/test_attachment_magic_validation.py`, `test_inline_image_attachment.py`, `test_attachment_service_phase2.py`, `test_internal_note_inline_image_attachment.py`, `test_cloud_link_attachment_extraction.py`, `test_attachment_never_inline.py`, and `test_interaction_service_attachment_load_error.py` could not be executed in this environment — importing the `python-magic` library crashes the Windows Python process with an access violation inside `magic/compat.py`, reproduced identically on a clean `git stash`ed tree with zero Phase 4 changes applied. This is a local libmagic/DLL environment issue on this machine, not a regression from this work — these files should be re-run in CI or a working local environment before merging, since they weren't verifiable here.

**Not yet done, still recommended (out of scope for this pass):** the manual live-Outlook checklist in Section K — code-level verification only, no real Outlook/Graph mailbox was available this session.

---

**End of report.**
