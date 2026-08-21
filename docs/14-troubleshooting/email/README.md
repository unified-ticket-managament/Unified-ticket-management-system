# Troubleshooting: Email

## Problem: Inbound attachments never arrive, even for valid files

**Symptoms**: Client emails with real PDF/DOCX/image attachments arrive with zero attachments visible in the Mail UI.

**Possible Causes** (three independent, stacked historical bugs — all confirmed and fixed, listed in case a similar-shaped new bug recurs):
1. `mail_mapping_service.py`'s `odata_type` gate rejected every attachment whose `@odata.type` was absent (which is every attachment, unless `$select` explicitly names that field).
2. `validators.py` rejected any attachment whose `content_type` didn't exactly match its extension's allow-listed MIME type — Graph legitimately reports `application/octet-stream` for some real files in this tenant.
3. **The real blocker**: `fetch_message_attachments`'s Graph call used a `$select` naming `contentBytes`, a property that only exists on the derived `fileAttachment` type — Graph's OData parser 400s on this for the base polymorphic `attachment` type. This 400 was being silently caught by a broad `except Exception` wrapper, so the email stored with zero attachments every time, with no visible error to the end user.

**How to Diagnose**: Check backend logs for a Graph API 400 on the attachments fetch call around the time of the affected email. Confirm the exact `$select` string being sent.

**Resolution**: All three were fixed (see root `CLAUDE.md`'s "Inbound Graph attachments" section) — `$select` was removed entirely from the attachment fetch call, the MIME check downgraded to log-only, and the odata_type gate now tolerates an absent value.

**Prevention**: If attachments silently vanish again, check for a Graph API error being caught by a broad exception handler before assuming the application-level validation logic is at fault.

**Edge Case — not a bug**: A file attached via Outlook's "Attach as cloud link" (OneDrive/SharePoint) never appears in Graph's `attachments` collection at all — this is fundamental to how cloud-linked attachments work, not something this pipeline can intercept.

**Related Documentation**: [16-known-limitations/integration-limitations.md](../../16-known-limitations/integration-limitations.md), [03-business-workflows/communication/incoming-email.md](../../03-business-workflows/communication/incoming-email.md).

---

## Problem: An OTP rule (or any Mail Rule) doesn't fire for the client its name implies

**Symptoms**: A rule named "OTP rule [Client X]" never triggers for Client X's emails.

**Possible Causes**: The rule's `client` condition, if present, is an **exact-match filter** — if it was edited (e.g. during testing) to reference a different client's id, it will silently never fire for the client the name implies, while correctly firing for whichever client it's actually configured for.

**How to Diagnose**: Open the rule in the Rules admin UI and check its exact `client` condition value against the client you expect it to match.

**Resolution**: Correct the `client` condition, or remove it entirely if the rule should apply company-wide (matching only on `subject_contains`/`body_contains`).

**Related Documentation**: [07-api/clients-categories-rules.md](../../07-api/clients-categories-rules.md).

---

## Problem: A forwarded email 403s when the recipient tries to open it

**Symptoms**: An internal user receives a `MAIL_FORWARDED` notification, but clicking it (or otherwise opening the item) returns "You do not have access to this item," even with `communication:view_all` granted.

**Possible Causes** (fixed 2026-08-15): `OpenEmailService.get_email_details`'s pending-item visibility gate (`ensure_agent_can_view_pending_interaction`) had no permission-claim check at all — only Site Lead/Super Admin or the client's own Account Manager were ever admitted, regardless of any granted permission.

**Resolution**: A `view_only=True` flag now additionally admits anyone holding `communication:view_all` for this specific read path — never widening claim/archive/reply/act authority on someone else's pending mail.

**Related Documentation**: [07-api/inbox-mail.md](../../07-api/inbox-mail.md), [03-business-workflows/communication](../../03-business-workflows/communication/).
