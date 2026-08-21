# Escalation AI Processing

## Status: Not Implemented

This document exists to satisfy the standard documentation structure (every workflow group gets a document per the source specification this documentation set follows) — but **no AI/NLP-based escalation processing was found anywhere in this codebase** during this documentation pass.

Specifically searched for and not found:
- Any LLM/AI API integration (OpenAI, Anthropic, or otherwise) in `unified-backend/app/ticketing/services/`.
- Any automated classification, summarization, or recommendation logic feeding the escalation decision (`_resolve_starting_level`, `_resolve_owners_with_fallback`) — escalation routing is entirely rule-based (role hierarchy + category + real ack-window timers), not model-driven.
- Any "AI-assisted" labeling in the frontend's escalation UI (`AcknowledgeAssignModal.tsx`, `SlaCard.tsx`).

## What does exist and might be conflated with this

- **Workload-based assignment ranking** — a design-only, unimplemented feature (see [17-roadmap/v2-roadmap.md](../../17-roadmap/v2-roadmap.md)) that would use rule-based scoring (open ticket count, SLA-risk exposure, category fit) — explicitly **not** an ML/regression-based recommender in its first proposed phase. An ML-based version is floated as a distinct, later "phase 2" idea in the design note, but no code exists for either phase.
- **The Mail/OTP Rules engine** (`RuleEngineService`) is condition-matching automation (subject/body/client string matching), not AI/NLP in any meaningful sense — don't conflate rule-based mail automation with "AI processing."

## Recommendation for future documentation

If AI/NLP escalation processing is ever built, this document should be replaced with a real workflow document following the standard template in [workflow-standards.md](../workflow-standards.md) — including which model/provider is used, what data crosses that boundary (see [08-security/ai-data-protection.md](../../08-security/ai-data-protection.md) for the PHI/PII considerations this would raise), and how a wrong/hallucinated recommendation is guarded against.

See also [04-functional-modules/ai-nlp.md](../../04-functional-modules/ai-nlp.md) for the module-level treatment of this same "not implemented" finding.
