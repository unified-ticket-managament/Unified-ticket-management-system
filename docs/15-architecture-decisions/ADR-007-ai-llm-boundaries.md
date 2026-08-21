# ADR-007: No AI/LLM Integration (A Documented Non-Decision)

**Status**: N/A — no decision has been made, because no such feature exists

## Context

This ADR slot is required by this documentation set's standard structure. Unlike the other ADRs in this section, there is no actual architectural decision to record here, because **no AI/LLM integration exists anywhere in this codebase** as of this documentation pass (confirmed by searching `requirements.txt`, every service file, and the escalation/assignment logic specifically, since those are the areas most likely to plausibly have one).

## What exists instead

- A design-only, unimplemented proposal for **rule-based** (not AI-based) workload scoring — see [17-roadmap/ai-automation-roadmap.md](../17-roadmap/ai-automation-roadmap.md). Its own design note explicitly defers any ML-based recommender to an unstarted "phase 2," separate from the rule-based first phase.
- The Mail/OTP Rules engine, which is condition-matching automation, not AI/NLP in any technical sense.

## Why this is worth documenting explicitly

Given this system's likely handling of PHI-adjacent healthcare billing communications (see [08-security/phi-pii-handling.md](../08-security/phi-pii-handling.md)), the *absence* of an AI boundary is itself a meaningful fact: there is currently no risk of client communication content being sent to a third-party AI provider, because no code path does that. If this ever changes, [08-security/ai-data-protection.md](../08-security/ai-data-protection.md) lists what should be established first, and this ADR should be replaced with a real decision record at that time — including the options actually considered (which provider, what data crosses the boundary, what compliance posture is needed).

## Recommendation

Do not backfill a decision rationale here that doesn't reflect an actual choice made — leave this ADR as a documented non-decision until a real one exists.
