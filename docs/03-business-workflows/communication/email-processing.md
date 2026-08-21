# Email Processing Workflow

## 1. Purpose
Turn a raw, mapped inbound email into a stored `Interaction`, matched to the right client, with First Response SLA tracking correctly initialized or completed, and evaluated against Mail/OTP automation rules.

## 2. Trigger
`EmailService.receive_email(email_request)`, called at the end of [incoming-email.md](incoming-email.md).

## 3. Actors
The system (no human actor).

## 4. Preconditions
A validated `EmailRequest` (sender, recipient, subject, body, headers, attachments).

## 5. High-Level Flow
Dedupe → identify client → thread (see [thread-detection.md](thread-detection.md)) → create Interaction → **classify for OTP and complete SLA if warranted** → evaluate Mail/OTP rules (independently).

## 6. Detailed Workflow
1. **Dedupe**: reject/ignore if `message_id` already stored.
2. **Client identification**:
   - Shared mailbox model: match sender address against `clients.inbox_email` or any `client_contacts.email`.
   - Legacy per-client dedicated inbox model: match by recipient address.
   - No match on a shared mailbox: route to Site Lead rather than reject.
3. **Threading**: resolve against `In-Reply-To`/`References` headers — see [thread-detection.md](thread-detection.md).
4. **Interaction creation**: one `interactions` row, `direction=INBOUND`, `interaction_type` set accordingly, `payload` holding body/metadata.
5. **First Response SLA effect (rewritten 2026-08-21 — now classifier-driven, not rule-driven)**: if this is a new thread root, a `FirstResponseSLA` row is created (`PENDING`, `due_at` from the client's priority-tier `SLAPolicy`). `EmailService.receive_email` then calls `otp_classifier.classify_otp_email(subject, body, threshold=settings.otp_nlp_confidence_threshold)` — a pure, dependency-free heuristic text scorer (see [04-functional-modules/ai-nlp.md](../../04-functional-modules/ai-nlp.md)) — **before the rule engine runs at all**. If the result clears the configured confidence threshold, `SLAService.complete_first_response_clock(interaction_id=root_interaction_id, completion_reason="OTP_RECOGNIZED")` fires immediately, inline, before commit — no external reader can ever observe a "started but not stopped" state for a matching email.
6. **Rule engine evaluation** (`RuleEngineService.evaluate_and_execute_for_email`), inline in the same transaction, runs afterward and **independently of step 5**: Mail Rules evaluated by priority first, then OTP Rules by priority — both stop-on-match per category (mirroring Outlook's own rule semantics). This still drives folder filing and `forward_to` employee notifications exactly as before. Its own `otp_recognized` return value is **no longer read for SLA purposes at all** — the two concerns were deliberately decoupled into two independent branches.

## 7. Business Rules
- **First Response SLA starts when the client's initial communication is received** — implemented by creating the `FirstResponseSLA` row at Interaction-creation time for a new thread root, never later.
- **OTP recognition driving SLA completion is now a semantic classification, not keyword rule-matching** (superseded 2026-08-21; the previous mechanism, "an OTP Rule match stops the clock," is documented in git history but no longer accurate). The classifier scores genuine delivery-intent signals — a qualifying code noun ("OTP," "verification code," etc.) plus a code-shaped 4-8 digit number are, together, sufficient on their own — against a hard confidence ceiling (0.30) whenever support-request/complaint framing is present ("unable to receive," "please investigate"). This is what lets "Unable to receive OTP — please investigate" correctly *not* complete the clock, a distinction a `body_contains: "OTP"` rule condition structurally cannot make.
- SLA completion via the classifier no longer depends on an admin having configured any OTP Rule at all — recognition now happens for *any* qualifying email, rule-configured or not.
- SLA completion is **provably independent of the Mail/OTP Rules engine**: it runs first, and a subsequent rule-engine exception (or a `forward_to` action failing) cannot affect a clock that has already completed.
- A Mail/OTP Rule's `client` condition, if present, is still an exact match for whatever the rule *does* control (folder filing, forwarding) — a misconfigured rule silently never forwards for the client its name implies, though this no longer has any bearing on SLA completion.

## 8. Decision Points
- New thread root vs. reply to existing thread → determines whether a new `FirstResponseSLA` is created or the existing thread's clock/ticket is targeted.
- Classifier confidence vs. `OTP_NLP_CONFIDENCE_THRESHOLD` → determines whether the First Response SLA auto-completes.
- Rule match found vs. not (a separate, later decision) → determines whether folder filing/forwarding fires.
- Client identified vs. not → determines normal routing vs. Site-Lead fallback.

## 9. Database Changes
- `interactions` — new row.
- `first_response_slas` — new row (new thread) or `status`/`completed_at`/`completion_reason="OTP_RECOGNIZED"` update (classifier match).
- Rule-triggered side effects (e.g. a forward creating a `Notification`), independent of the above.

## 10. APIs Involved
None directly — this is an internal pipeline step, not an HTTP endpoint. Surfaced to users via `GET /inbox`, `GET /inbox/{id}` (both now return the real, already-completed clock state, not a client-estimated countdown).

## 11. Services / Components Involved
`EmailService.receive_email`, `app/ticketing/services/otp_classifier.py` (`classify_otp_email`), `RuleEngineService`, `SLAService.complete_first_response_clock`, `FirstResponseSlaRepository`.

## 12. External Integrations
None directly (upstream transport already handled in [incoming-email.md](incoming-email.md)). The classifier itself makes no external call of any kind — pure, local, deterministic scoring.

## 13. Notifications
A Mail/OTP Rule match with a successfully-resolved `employee_user_ids` list creates an `OTP_FORWARDED` notification and attempts a real send; a stale/deactivated employee id in the rule silently skips the forward (logged warning) — entirely independent of whether the SLA already completed via the classifier.

## 14. Audit Events
Not directly — Interaction creation itself isn't a `ticket_audit_logs` event (that table is ticket-scoped); a ticket doesn't exist yet at this stage for most new mail.

## 15. Failure Scenarios
See [incoming-email.md](incoming-email.md)'s Failure Scenarios for transport-level issues. At this stage: a rule referencing deleted/deactivated employees fails silently for the forward action only — this cannot affect SLA completion, which happens in an earlier, independent step.

## 16. Edge Cases
- A reply to an existing thread does not create a new `FirstResponseSLA` — it's resolved to the thread root's existing clock.
- A borderline OTP email with no expiration wording at all can still classify correctly — expiration language is a confirmatory bonus signal, not required, specifically because a real inbound test email without it was found during this feature's own calibration.
- An email matching a Mail/OTP Rule scoped (via its `client` condition) to the *wrong* client silently never forwards for the client its name implies — a real, confirmed historical incident (see root `CLAUDE.md`'s OTP section) — but as of 2026-08-21 this no longer affects SLA completion at all, only the forwarding action.
- The pre-existing guarantee that a `COMPLETED` First Response SLA clock can never later re-enter At-Risk/Breached/Escalated processing (`FirstResponseSlaRepository`'s active-clock query filters on `status == PENDING`, and completion is an idempotent no-op if already completed) was untouched by this rewrite and still holds.

## 17. Postconditions
A stored, client-attributed, threaded `Interaction` exists; the First Response SLA clock is either running or already completed as appropriate; any matched Mail/OTP Rule automation has fired, independently of the SLA decision.

## 18. Relevant Source Files
- `unified-backend/app/ticketing/services/{email_service,otp_classifier,rule_engine_service,sla_service}.py`
- `unified-backend/app/ticketing/repositories/first_response_sla_repository.py`
- `unified-backend/app/core/config.py` (`otp_nlp_confidence_threshold`)
- `unified-backend/tests/{test_otp_classifier,test_email_service_otp_sla_completion}.py`

## 19. Example Scenario
A client's automated system emails a one-time passcode ("Your verification code is 482913") to the shared support mailbox. `classify_otp_email` scores the code-noun phrase (0.55) plus the code-shaped number (0.40) — 0.95, clearing the 0.90 threshold — and the First Response SLA clock completes immediately with `completion_reason="OTP_RECOGNIZED"`, before the rule engine has even run. Separately, and independently, a configured OTP Rule matching the same email still forwards it to configured employees via `OTP_FORWARDED` — two unrelated outcomes from two unrelated mechanisms. A different email, "Unable to receive OTP, please investigate," would score the same two base signals but hit the 0.30 support-request ceiling and never complete the clock.
