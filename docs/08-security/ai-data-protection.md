# AI Data Protection

## Status: Not Applicable — no AI/LLM integration exists in this system

Per [04-functional-modules/ai-nlp.md](../04-functional-modules/ai-nlp.md), no AI or NLP capability (classification, drafting, summarization, escalation processing) was found anywhere in this codebase. Consequently, there is no data boundary to document today — no client communication, PHI, or PII currently crosses into a third-party AI provider's API.

## What to check before this becomes applicable

If an AI/LLM feature is ever added to this system (e.g. the floated "phase 2" ML-based workload/resolution-time recommender mentioned in the roadmap — see [17-roadmap/ai-automation-roadmap.md](../17-roadmap/ai-automation-roadmap.md)), the following should be established **before** shipping it, given this system's likely handling of PHI-adjacent client data (see [phi-pii-handling.md](phi-pii-handling.md)):

1. **What data crosses the boundary.** Does the feature send raw email bodies/attachments to an external model, or only derived/aggregate signals (e.g. "ticket count," "elapsed SLA fraction")? The latter carries far less risk.
2. **Which provider, and under what agreement.** A BAA (or equivalent) would likely be needed if PHI could ever reach the request payload.
3. **Data retention on the provider side.** Whether the provider retains/trains on submitted data by default, and whether that can be disabled.
4. **Logging of AI requests/responses.** Whether prompts/completions get logged anywhere in this system (potentially duplicating PHI exposure into a second, less-governed store).
5. **A clear audit trail** for any AI-influenced action (e.g. a recommended assignment that a supervisor accepted) — this system already has strong precedent for "the system decided X, log it as `ActorRole.SYSTEM`" (the CRITICAL-priority bump), which would be a reasonable pattern to extend.

## Recommendation

Update this document with real content the moment any AI/LLM integration is proposed or built — don't let it stay a placeholder once it's no longer accurate.
