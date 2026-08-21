# Regression Testing

Tests in this suite that exist specifically because a real, confirmed bug happened once — the strongest evidence of this codebase's actual quality-assurance philosophy (fix it, then add a test that would have caught it).

| Test file | The bug it guards against |
|---|---|
| `test_attachment_upload_authorization.py` | `AttachmentService.upload_attachment`'s authorization check being called without `await` — a coroutine created and immediately discarded, silently never running, letting any authenticated agent upload to any ticket. |
| `test_acknowledge_and_assign_escalation.py` | Acknowledging alone silently restarting the Resolution SLA/Handling SLA against nobody's actual ownership; `acknowledge_via_assignment`'s bail-out incorrectly blocking the most common real path (Acknowledge, then Assign). |
| `test_view_escalated_permission.py` | The Escalated tab/Acknowledge action surfacing (and being actionable) for overseer roles before an escalation chain had actually reached them. |
| `test_ticket_number.py` | The `TKT-01`...`TKT-06`, `TKT-187` stale-backfill numbering bug, and the general "no duplicates under concurrent creation" guarantee. |
| `test_get_current_user_cache.py` | Correct cache-hit/miss/staleness behavior for the RBAC session cache, including the `permission_version`-mismatch rejection path. |
| `test_organization_chart_hierarchy.py` | The org chart showing only `Super Admin -> them` for an Account Manager's own profile, instead of the full dynamic chain, before the per-profile rewrite. |
| `test_internal_note_recipients.py` | Three stacked bugs found in the same feature pass: a missing `payload` trim-through, a missing `NotificationService` construction on the notes route, and Staff's 403 on the old hierarchy-scoped recipient picker. |
| `test_notification_email_dispatch.py` | Ensures only the intended notification types email, inactive users are skipped, and a transport failure never blocks the already-created notification row. |
| `test_sla_sweep_auth.py` | The shared-secret auth on the manual sweep-trigger endpoint, using constant-time comparison. |
| `test_escalation_service_email_dedup.py` | Ensures escalation owner notification goes through the single `NotificationService` path, never a second, direct-email code path. |
| `test_otp_classifier.py` / `test_email_service_otp_sla_completion.py` | The false-positive gap in the previous keyword-rule-based OTP detection: a support complaint mentioning "OTP" (e.g. "Unable to receive OTP — please investigate") could incorrectly complete the First Response SLA clock. Fixed 2026-08-21 by replacing the trigger with a heuristic classifier scoring genuine delivery-intent signals against a hard confidence ceiling for complaint framing. |

## Why this matters for future work

When fixing a new bug in this codebase, the established convention is clear: **add a test that reproduces the exact failure mode, not just a test that exercises the fixed code path in the happy case.** This is what makes the existing 46-file, 491-test suite as valuable as it is for its size — it's disproportionately weighted toward the exact scenarios that have actually gone wrong in production/dev, rather than generic coverage.

## A known false regression source

`test_overdue_active_escalation_advances_without_touching_sla`'s flake (see [integration-testing.md](integration-testing.md)) is **not** evidence of a real regression if it fails — it's dev-data debris in a shared, never-reset database. Don't let this specific failure trigger a bug hunt; do let it prompt eventually fixing the test's own isolation assumption.
