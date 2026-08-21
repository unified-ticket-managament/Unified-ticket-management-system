# Integration Limitations

## Microsoft Graph attachment fetching required removing `$select` entirely

**Limitation** (historical, fixed): Graph's `/messages/{id}/attachments` endpoint 400s if `$select` names `contentBytes` (a property that only exists on the derived `fileAttachment` type, not the base polymorphic `attachment` type Graph's OData parser validates `$select` against). The fix removed `$select` from this call entirely — meaning every attachment fetch now transfers the full object rather than a trimmed one.
**Impact**: Slightly more data transferred per attachment-list call than a working `$select` would allow; no workaround exists within Graph's current OData behavior for this tenant/API version.
**Why It Exists**: A Graph API/OData constraint, not an application design choice.
**Current Workaround**: N/A — this is the fix.
**Is It Planned?**: N/A — resolved as far as it can be.

## OneDrive/SharePoint "cloud link" attachments are invisible to the pipeline

**Limitation**: Outlook's "Attach as cloud link" behavior inserts an HTML anchor into the email body instead of a real Graph `fileAttachment` — Graph's `attachments` collection never contains it at all.
**Impact**: An email attached this way shows zero attachments in the Mail UI even though a file link is embedded in the body.
**Why It Exists**: Fundamental to how Outlook implements cloud-linked attachments; not something the attachment pipeline can intercept.
**Current Workaround**: None — would require a different feature (rendering body-embedded cloud links as pseudo-attachments).
**Is It Planned?**: Investigated, not attempted.

## Email delivery for business-critical notifications is allowlist-gated and not fully live-verified

**Limitation**: The email-on-notification feature (`EMAIL_ELIGIBLE_NOTIFICATION_TYPES`) is verified only via a pure-logic unit test suite (no DB, no SMTP) — it has not been confirmed against a real SMTP server or a running backend end-to-end.
**Impact**: Treat outbound business-critical email as **unit-tested but not production-proven** until that check is done.
**Why It Exists**: No SMTP server / running backend was available in the session that built this feature.
**Current Workaround**: Do the live check (real SMTP, real backend) before relying on it in production incident response.
**Is It Planned?**: Explicitly flagged as a follow-up verification step, not a code task.

## SMTP/Graph both safely no-op when unconfigured

**Limitation**: If `smtp_host` (or equivalent Graph mail settings) is left unset, outbound email falls back to logging-only, and Graph mail polling presumably has an equivalent disabled/mock state (see [05-technical-architecture](../05-technical-architecture/README.md) for the actual mock-provider behavior — verify in code before relying on this description).
**Impact**: A misconfigured or missing SMTP/Graph setting fails silently (log-only) rather than raising an error — worth checking configuration explicitly rather than assuming email/mail integration is active.
**Why It Exists**: Deliberate graceful-degradation design for local dev without real credentials.
**Current Workaround**: Check `unified-backend/app/core/config.py`'s `Settings` for whether SMTP/Graph fields are populated in a given environment.
**Is It Planned?**: N/A — working as designed.

## Storage backend choice (Supabase vs S3) is a single global setting

**Limitation**: `STORAGE_BACKEND` is one setting (`supabase` or `s3`) for the whole deployment — not per-tenant or per-file-type configurable.
**Impact**: Migrating storage backends requires a coordinated cutover, not a gradual one.
**Why It Exists**: Simplicity of a single-tenant-style deployment.
**Current Workaround**: N/A.
**Is It Planned?**: Not confirmed.
