# AI / Automation Roadmap

## Current state: no AI/automation beyond condition-matching rules

See [04-functional-modules/ai-nlp.md](../04-functional-modules/ai-nlp.md) and [15-architecture-decisions/ADR-007-ai-llm-boundaries.md](../15-architecture-decisions/ADR-007-ai-llm-boundaries.md) — no AI/LLM integration exists in this codebase today.

## Phase 1 (Planned, design-only): rule-based workload scoring

See [v2-roadmap.md](v2-roadmap.md) for the full design — a `GROUP BY agent_id` aggregate scoring layer (open ticket count weighted by priority, SLA-risk exposure, active escalations owned), explicitly **not** machine-learning based. No code exists yet.

## Phase 2 (Floated, not designed, not started): ML-based resolution-time recommender

The same design note that describes Phase 1 explicitly calls out a **separate, later idea**: predicting resolution time per agent/category/priority via a regression/ML model. This was deliberately deferred — described as "a real phase-2 idea but a separate epic — data pipeline, training, drift monitoring — not to be folded into the same change as the rule-based scorer." No further design work exists beyond this one sentence of scope-deferral.

## What would need to happen before Phase 2 could start

1. A real design pass (data pipeline, feature engineering, model choice, training/retraining cadence, drift monitoring) — none exists today.
2. An availability/shift-presence data model — doesn't exist, and Phase 1's own design note already flags this as a prerequisite gap for even the rule-based "filter unavailable candidates" step.
3. A data-protection review per [08-security/ai-data-protection.md](../08-security/ai-data-protection.md), given this system's likely PHI-adjacent data.

## Recommendation

Treat Phase 2 as genuinely unscoped — resist the temptation to treat the one-sentence mention in root `CLAUDE.md` as a real plan. If this work is ever picked up, it should start with a fresh design document, not an extension of the Phase 1 rule-based scorer's own code.
