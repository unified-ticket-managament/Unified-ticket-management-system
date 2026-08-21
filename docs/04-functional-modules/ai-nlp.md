# AI / NLP Module

## Status: One real, narrow text-classification feature exists (added 2026-08-21) — no machine learning or LLM integration exists anywhere else

This document was previously "Not Implemented" in full. That is no longer accurate for one specific capability: **semantic OTP email classification**. Everywhere else in the system (escalation routing, assignment, dashboards) remains pure rule/threshold-based logic, unchanged — see [03-business-workflows/escalation/escalation-ai-processing.md](../03-business-workflows/escalation/escalation-ai-processing.md).

## What exists: the OTP classifier

**Purpose**: Distinguish a genuine one-time-passcode delivery email from an email that merely *mentions* "OTP" (e.g. a client's support complaint: "Unable to receive OTP — please investigate"), so the First Response SLA clock only auto-completes for the former.

**Important framing**: despite being called a "semantic classifier" in its own code comments, this is **not** a machine-learning model and **not** a call to any external NLP/LLM API. `app/ticketing/services/otp_classifier.py`'s `classify_otp_email()` is a pure, dependency-free, deterministic function — regex pattern matching plus fixed weighted scoring, no training data, no model file, no network call. A codebase-wide scan (part of this feature's own build) confirmed no AI/LLM dependency exists anywhere in this backend, and none was added to build this.

**How it scores** (weights confirmed from source):
- A qualifying code-noun phrase ("OTP," "verification code," "one-time password," "passcode," etc.) — weight 0.55.
- A code-shaped 4-8 digit number appearing in the text — weight 0.40.
- These two together are sufficient on their own to clear the default 0.90 threshold — a genuine code delivery essentially always carries both, while a complaint about a *missing* OTP essentially never repeats the customer's own numeric code.
- A usage-instruction phrase ("enter this code to complete your login") — +0.20, confirmatory bonus, not required.
- Expiration language ("expires in 10 minutes") — +0.15, confirmatory bonus, not required (real OTP emails often omit this entirely — confirmed against a real inbound test email with no expiration wording, which is why this isn't a required signal).
- A **hard confidence ceiling of 0.30** applies whenever support-request/complaint framing is present ("unable to receive," "please investigate," "please check," a "Ticket #"/"Case #" reference) — this overrides any coincidental keyword overlap, and is what actually solves the false-positive problem plain keyword matching couldn't.

**Where the threshold lives**: `Settings.otp_nlp_confidence_threshold` (default `0.90`) is a runtime config setting, not a constant inside the classifier — the classifier only returns a confidence score; the caller (`EmailService.receive_email`) decides what counts as "confident enough."

**What it replaced**: previously, `otp_recognized` was set purely by `RuleEngineService`'s keyword/substring rule matching (a `body_contains: "OTP"` condition) — this could not distinguish a genuine code delivery from a mere mention, and was entirely dependent on an admin having configured a matching rule at all. `EmailService.receive_email` now completes the Response SLA from the classifier's output alone, **before** the Mail/OTP Rules pass even runs — provably independent of, and never gated on, the rule engine or its forwarding action. See [03-business-workflows/communication/email-processing.md](../03-business-workflows/communication/email-processing.md) for the full mechanics, and note that `RuleEngineService`/Mail-OTP-Rule forwarding itself is completely unchanged and still runs — it simply no longer has any bearing on SLA completion.

## What was specifically searched for and NOT found (still accurate)

- No ticket classification, response drafting, sentiment analysis, or summarization logic.
- No AI-assisted escalation-processing logic — escalation routing is entirely rule-based (role hierarchy, category, real timers).
- `.deepeval/` at the repo root is still a completely empty scaffold — not wired to anything, including not to this classifier (which has its own plain pytest unit tests instead, see [11-testing](../11-testing/README.md)).

## What might be conflated with "AI" but isn't

- **Mail/OTP Rules engine** (`RuleEngineService`) — condition-matching automation, unchanged, still purely rule-based.
- **Workload-based assignment ranking** — still design-only, still explicitly scoped as rule-based in its proposed first phase (see [17-roadmap/v2-roadmap.md](../17-roadmap/v2-roadmap.md)).

## Recommendation

If a genuine ML/LLM capability is ever added, update this document with real content and add a corresponding entry to [08-security/ai-data-protection.md](../08-security/ai-data-protection.md) — the OTP classifier above doesn't trigger that concern (it's local, deterministic, and never sends data anywhere external), but a future model-backed feature would.
