# Architecture Reconciliation Report

**Scope**: this document reconciles two things already produced in this project:

1. **The existing benchmark architecture** — `RCM_TICKETING_KNOWLEDGE_BASE.md` (business/domain brief) + `ML_TICKETING_SCHEMA_REFERENCE.md` (code-verified schema reference), both written specifically to support building a small, curated synthetic dataset + evaluation query set for a not-yet-built **AI Ticket Recommendation** feature.
2. **The production application architecture** — `RCM_APPLICATION_KNOWLEDGE_BASE.md`, a full code-verified specification of the actual running application, produced separately and more broadly.

**Confirmed before writing this report**: there is no generator code, benchmark harness, or dataset anywhere in this repository yet (checked — no matches for `*synthetic*`, `*benchmark*`, `*recommendation*`, `*eval*.py` outside library internals, and no `ticket-recommendation.pdf` file present despite being referenced by the first document). "The existing benchmark architecture" therefore means **the documented design**, not existing code — which is exactly the right moment to reconcile it, before any generator is built.

**A load-bearing fact that shapes this entire report**: both the benchmark schema reference and the production knowledge base were derived from a direct read of the *same* source code (`unified-backend/`, `shared_models/`). They are not two competing designs — the benchmark document is a **deliberately narrowed subset** of the exact same schema, scoped to what one ML feature needs. This means Section 1 below is not really about resolving contradictions (there are none at the column/type level) — it's about **scope**: what the benchmark document correctly left out *for its narrow purpose*, and what a production-aligned environment needs to add back in.

**This document does not propose implementation.** It ends at a roadmap (§6) — no schema is finalized, no generator is designed, no code is written.

---

## 1. Schema Differences

### 1.1 Summary table

| Entity | Verdict | Why |
|---|---|---|
| `categories` | **Directly reusable** | Fixed 7-row lookup, identical shape/purpose in both documents (same source). No divergence possible. |
| `clients` | **Directly reusable** | Same shape and role in both — a company with one `inbox_email` and one owning Account Manager. The benchmark's own "one client, many plausible senders" rule already matches production's actual sender-matching behavior. |
| `sla_policies` | **Directly reusable** | 4-row global lookup; both documents already independently agree to use the *intended/migrated* values, not the live demo-drifted MEDIUM row — see production doc §19.3. |
| `roles` / `permissions` / `role_permissions` | **Directly reusable (as seed data)** | The benchmark called these "not needed at all" — correct for a recommendation-only dataset, but a production-aligned environment needs a valid actor graph for every action to be authorizable. The fix is not new design: reuse the real seed script's roles/permission matrix verbatim. |
| `users` | **Requires modification** | Benchmark: "at least one of each role per category" — an FK anchor, nothing more. Production: users are a validated organizational entity (`manager_id`/`teamlead_id` role-and-category consistency, Reporting Manager mapping, `permission_version`, ten profile columns). Needs richer generation, not a new shape. |
| `interactions` | **Requires modification** | Benchmark only generates `EMAIL`/`REPLY`/`INTERNAL_NOTE`. Production's real state space also includes `ATTACHMENT` rows, `is_draft` (with the one-active-draft-per-thread invariant), `claimed_by`/`claimed_at`, `folder_id`, `is_visible` soft-delete, and a `payload.dispatch_status` state machine (`QUEUED → SENT/FAILED`, or `DRAFT`). |
| `tickets` | **Requires modification (in usage, not shape)** | Column-for-column identical in both documents (same source). The gap is *internal consistency*: benchmark tickets are independently-sampled rows; production tickets must have `current_status`/`current_priority`/`agent_id` that are the actual, derivable consequence of their own interaction/audit/SLA history. |
| `resolution_slas` | **Requires modification** | Benchmark: optional, static, "skip entirely if out of scope." Production: a genuinely temporal clock — pause/resume/reshift/restart must produce internally consistent `due_at`/`status`/`escalation_cycle`, not sampled values. |
| `first_response_slas` | **Requires modification** | Same reasoning, one-shot version — `due_at` must derive from the paired interaction's real `received_at`, not be sampled independently. |
| `attachments` | **Requires modification** | Benchmark: optional, simple. Production: real validation ceiling (25MB/file, 10 files/upload, allow-listed MIME types) that synthetic data should respect for realism, even though `scan_status` can stay a permanent stub in both (production itself never reads it either). |
| `ticket_escalations` | **Requires modification** | Benchmark: optional inert metadata ("only if modeling escalation-aware recommendations"). Production: a live chain with a real starting-level rule, ack-window auto-advance, and handling-stage restart — can't be stamped as a static level, must be internally derived from the Resolution SLA's own breach history. |
| `escalation_handling_slas` | **Requires modification, and should be merged at the *generation* level (not the schema level)** | Production itself already treats this table as a dual-write, non-authoritative mirror of state that really lives on `ticket_escalations.handling_stage`. A generator should author `ticket_escalations` as the one source of truth and *mechanically derive* this table's rows from it, rather than hand-authoring both independently — same pattern production's own code follows. The two tables stay schema-distinct (production doesn't merge them, so neither should the synthetic environment). |
| `ticket_audit_logs` | **Requires modification** | Benchmark: "useful for realistic timestamps... otherwise skippable" — implies independent sampling. Production: this is the evidentiary trail of every other table's mutations. If generated independently of the actions that supposedly produced it, it will visibly contradict the very tickets/interactions/SLA rows it describes. Must become a byproduct of history generation, not a peer table. |
| `ticket_relations` | **Requires modification, with a conceptual warning attached** | The benchmark doc itself flags this table as "the closest existing analog to what a recommendation system produces." That framing is useful context but a real risk: this table must stay what it is in production — a sparse, manual, symmetric "an agent said these are related" link — and must **not** be quietly repurposed as the output store for the AI Recommendation Layer (§5). If the recommendation feature ever writes here, that's a real product decision to make explicitly, not an artifact of synthetic-data convenience. |
| `sla_breach_notifications` | **Newly identified gap — requires addition** | Not mentioned anywhere in the benchmark document's required, optional, *or* excluded lists — a genuine omission, not a deliberate exclusion. This is the idempotency ledger the real SLA sweep depends on to avoid re-notifying every tick; any production-aligned simulation of the sweep needs it or will misbehave (duplicate notifications, wrong `escalation_cycle` re-firing). |
| `notifications` | **Requires modification (from excluded to required, as a byproduct)** | Benchmark: excluded as "pure plumbing, irrelevant to ticket content." True for the recommendation task in isolation; false for a production-aligned world, since notifications are a direct, visible consequence of nearly every business action modeled elsewhere in this schema. Should never be independently sampled — only ever generated as the side effect of whatever process generates the triggering action. |
| RBAC-native `audit_logs` | **Requires modification (same reasoning as `notifications`)** | Excluded in the benchmark as irrelevant to ticket content — true narrowly, but production-aligned fidelity means login/permission-change history should exist consistently alongside the user graph it describes. |
| `reporting_manager_teams`, `permission_requests`, `user_permission_overrides`, `ticket_edit_access_requests`, `mail_folders` | **Requires modification (from wholly excluded to sparsely populated)** | These gate real but comparatively rare admin/edge-case workflows (HR-adjacent reporting-manager assignment, permission exception requests, cross-agent edit-access grants, mail folder tagging). They matter for org/admin realism but are not central drivers of ticket/SLA/escalation behavior — populate thinly rather than either ignoring them (benchmark's choice) or over-investing in them. |
| Computed-only `Ticket` fields (`is_escalated`, `escalation_level`, `resolution_sla_tier`, etc.) | **Confirmed: correctly excluded already — no change, restated as a validated finding** | The benchmark document already correctly warns these must never be modeled as real stored columns. This still holds in the production-aligned world: they must be derived at read time exactly as the real app derives them, never persisted. |
| Message-intent content patterns (Initial Request / Documentation Provided / Follow-up / Escalation / Thank-you) | **Should NOT be split into a schema column — remains a generation-time authoring guideline only** | Production has no such column; `Interaction.payload` is free-form JSON with no intent classifier field anywhere in the real schema. Introducing one to make content generation easier would itself be a production-fidelity violation. This taxonomy should live in the *generator's own prompting/authoring logic*, never in the data model. |
| Eval query set, `should_match` labels, difficulty tiers (Easy/Moderate/Hard Semantic/Same-Customer Disambiguation/Hard Negative/Boilerplate) | **Should remain benchmark-only** | No production table stores a "query" or a correctness label — these are pure test-harness artifacts for scoring an algorithm's output against known-correct answers. They belong entirely to the Research/Benchmark Layer (§3, §5). |
| Recommendation logs/feedback table, `ticket_embeddings`/vector storage | **Should remain benchmark-only for now** | Proposed in the benchmark document's own "Future Compatibility" section as *net-new* additions — neither exists in production today (confirmed independently by both source documents via repo-wide search). These belong to the AI Recommendation Layer (§5) until/unless the real feature ships and they become genuine production tables — a decision explicitly out of scope here. |

### 1.2 Headline findings

- **No entity requires renaming.** Since both documents were derived from the same source, naming is already consistent everywhere. This is a reassuring, non-obvious result worth stating plainly: reconciliation work here is about *scope and internal consistency*, not translation.
- **No entity should be removed** from the reused core schema — every table the benchmark document considered still has a legitimate place; the changes are about which ones move from "excluded/optional" to "included," and how richly each is populated.
- **The one genuine "split" question** (message-intent as a column vs. a generation-time label) resolves in favor of **not** touching the schema — the taxonomy stays a content-authoring tool, never becomes a stored field.
- **The one genuine "merge" question** (`ticket_escalations` vs. `escalation_handling_slas`) resolves at the *generation* layer, not the schema layer — author one, mechanically derive the other, exactly mirroring how the real application's own code already treats the second table as a non-authoritative mirror.

---

## 2. Pipeline Differences

The benchmark document never actually describes a "pipeline" in the sense of a running process — it describes a **generation order** for a one-time, static batch (§7/§9 of `ML_TICKETING_SCHEMA_REFERENCE.md`: Client → founding Interaction → Ticket → optional SLA rows), sized for a small, curated corpus (~15–20 clients, ~50–100 tickets) plus a separately-authored eval query set (~150–250 queries). Production, by contrast, is a **live, event-driven, continuously-ticking system**: real-time email intake with dedupe/thread-matching, a periodic SLA sweep that mutates state every tick (pause/resume/reshift/restart clocks, auto-escalate, auto-advance escalation levels), notification fan-out, and an audit trail that accretes continuously. This is the single biggest conceptual gap between the two architectures — a **static-snapshot generation model** versus an **inherently temporal, event-sourced production system**.

### 2.1 Reusable components (lift as-is)
- **The generation-order invariant**: Client → founding Interaction → Ticket → SLA clocks. This is a hard DB-level constraint in production (a Ticket cannot exist without a prior Interaction) — it doesn't change regardless of whether the environment is static or dynamic.
- **RCM-domain content generation approach**: the glossary-grounded, category-specific issue-type vocabulary and the message-intent-driven multi-turn thread structure are fully reusable as the *content* layer, independent of whatever generation mechanism produces the surrounding rows.
- **Reuse-real-seeded-lookup-tables principle**: don't regenerate `categories`, `roles`/`permissions`, or `sla_policies` — reuse the real seed data. The benchmark document already established this correctly for the tables it considered; it simply needs to be extended to the RBAC tables it previously excluded.
- **Sample record JSON shapes** (§10 of the schema reference) — still schema-accurate templates, reusable as a starting structure for whatever generator is eventually built.

### 2.2 Obsolete assumptions (must be dropped, not carried forward)
- **"A single snapshot in time, all tickets current."** SLA clocks tick, escalations advance on a schedule, and notifications fire continuously in the real system — a static snapshot cannot represent this behavior at all; it can only represent a frozen instant that happens to look plausible.
- **Fixed small scale (15–20 clients / 50–100 tickets).** That sizing was chosen for a curated, well-labeled retrieval-eval set — a reasonable choice for that purpose — but it says nothing about what volume a production-aligned operational world needs to meaningfully exercise SLA-sweep behavior, concurrent escalations, or notification fan-out under load.
- **"RBAC/permissions are irrelevant plumbing."** True only when the sole consumer is a content-similarity algorithm. Once the environment needs to be production-aligned, every ticket action is permission-gated, so a coherent actor/permission graph is a prerequisite, not an optional extra.
- **"Notifications/audit logs are irrelevant plumbing."** Same reasoning — they're real, visible, continuously-produced byproducts of business actions in production; a world without them doesn't behave like production, it behaves like a database dump.
- **The implicit assumption that a Ticket's fields can be independently sampled.** Once RBAC, SLA, and escalation are all in scope together, `current_status`, `current_priority`, `agent_id`, and the SLA/escalation rows attached to a ticket are no longer independent — they must be mutually consistent outcomes of one coherent history.

### 2.3 Components that remain valid (as design principles, not lift-able artifacts)
- "A ticket cannot exist without a founding interaction" — still an absolute invariant.
- "Category is the only classification axis on a ticket, and it's a soft string, not an FK" — still true, still worth preserving deliberately in synthetic data rather than "fixing" it.
- "No separate `IssueType` concept exists" — still true; don't invent one for generation convenience.

### 2.4 Components that require redesign
- **Ticket creation must go through (or faithfully emulate) the real service-layer sequence**, not independent row inserts. In production, `InboxTicketService.create_ticket_from_interaction` atomically ties together thread-matching, an audit-log write, and starting/completing both SLA clocks. A generator that inserts a `Ticket` row without also producing the matching audit row and SLA-clock side effects will silently diverge from the invariants the rest of this schema depends on.
- **SLA/escalation state needs a temporal generation strategy that doesn't exist in the benchmark design at all.** Two candidate shapes (a decision for a later document, not this one): (a) a simulated sweep that replays the real `SLASweepService.run_sweep` logic over a fabricated timeline, or (b) seeding data into a real, isolated running backend instance and letting its actual scheduler produce the operational history organically. The benchmark pipeline has no analog to either.
- **Notification and audit-log generation must be a byproduct, not an independent sampling step.** The benchmark pipeline never considered generating either (they were on its "not needed" list) — a production-aligned pipeline needs a component that produces them consistently, ideally by construction rather than by separate, potentially-inconsistent synthesis.
- **Action validity now depends on the actor graph.** Every generated business event (a reply, a transfer, an escalation acknowledgment) needs an actor whose role/permissions/category genuinely allow that action in the real system — a new validity constraint the benchmark pipeline never had to satisfy.

---

## 3. Research vs. Production

### 3.1 Research Layer (benchmark-only — no production analog, and none should be created for its own sake)

| Item | Why it belongs here |
|---|---|
| Eval query set (the actual test queries) | Production has no concept of a "query" — this exists purely to exercise a not-yet-built matching algorithm. |
| `should_match` ground-truth labels | Only meaningful as a scoring target against a known-correct answer; no ticket in production carries a "this is the correct match" field. |
| Difficulty tiers (Easy/Moderate/Hard Semantic/Same-Customer Disambiguation/Hard Negative/Boilerplate) | A test-design taxonomy, not a business concept — no ticket or interaction is ever tagged with a "difficulty" in the real system. |
| Recommendation logs / feedback table (proposed) | Would only ever exist to support ML iteration (what was shown, was it accepted) — no operational meaning to an agent using the real ticket system today, since no such feature is deployed. |
| `ticket_embeddings` / vector storage (proposed) | Pure ML infrastructure, orthogonal to the business schema; confirmed absent from production by direct repo search. |
| Scale/sizing assumptions (15–20 clients, 50–100 tickets, 150–250 queries) | A benchmark-curation decision, not a claim about realistic production volume — must not be silently reused as the sizing for the Production Operational Layer. |

**Why the separation matters**: Research Layer artifacts are bound to a specific benchmark task and will need to be re-labeled or regenerated as the recommendation feature (or its definition of "correct") evolves. They should be versioned and iterated independently of the operational data they're evaluated against, not baked into the same generation pass.

### 3.2 Production Operational Layer (belongs in the synthetic environment because it drives real application behavior)

Everything catalogued in `RCM_APPLICATION_KNOWLEDGE_BASE.md` §5 (both the RBAC and ticketing Alembic domains), specifically because:
- **SLA/escalation temporal behavior** drives real notifications, real audit trail entries, and a real permanent priority change (the CRITICAL bump) — it cannot be treated as inert metadata once the environment claims to be production-aligned.
- **The RBAC/permission graph** gates literally every ticket action in the real system — a synthetic world without a coherent user/role/permission graph cannot validly answer "who can do what," which undermines any downstream use (automation testing, workload analysis, security testing) beyond the recommendation feature.
- **Notifications and audit logs** are real operational exhaust — any future automation project (see §5's "Future Automation Projects" layer, and the automation ideas already discussed earlier in this project) will likely need to read them as ground truth, not just the recommendation feature.

**Why the separation matters**: the Production Operational Layer aims to be a *stable, reusable substrate* — something other future projects can build on without caring about the recommendation benchmark's specific needs. Coupling it to the Research Layer's assumptions (small scale, static snapshot, no RBAC) would make it useless for anything else.

---

## 4. Migration Strategy

**Explicitly not a rebuild.** The goal is maximum reuse of the two existing documents' genuinely reusable content, with the scope corrections identified in §1–§3 layered on top.

### 4.1 Preserve as-is
- The RCM domain glossary and category-to-issue-type mapping (§2 of the benchmark business brief) — pure business content, orthogonal to every schema/pipeline concern raised here.
- The generation-order invariant (Client → Interaction → Ticket → SLA clocks).
- The reuse-real-seeded-lookup-tables principle — now simply extended to cover `roles`/`permissions`/`role_permissions` as well as `categories`/`sla_policies`.
- The sample-record JSON shapes — still schema-accurate.
- The message-intent content-authoring patterns — reusable as a generation technique at any scope.
- Both existing documents themselves — **do not rewrite `ML_TICKETING_SCHEMA_REFERENCE.md` or `RCM_TICKETING_KNOWLEDGE_BASE.md`.** They remain accurate, narrowly-scoped references for the recommendation research effort specifically. This report and `RCM_APPLICATION_KNOWLEDGE_BASE.md` are additive layers alongside them, not replacements.

### 4.2 Refactor (kept, but restructured/extended)
- The "minimal viable table set" framing — reframe from "minimal for one ML feature" to two independently-tunable table sets: an **operational core** (always populated, production-aligned) and a **research extension** (the eval/labeling artifacts), with the dividing line drawn per §3 above rather than per "does the recommendation feature need it."
- The scale assumption — split into two independently-tunable parameters: a Production Operational Layer scale (sized for realistic volume / stress behavior) and a Research Layer scale (sized for a curated, well-labeled eval set — the existing 15–20 / 50–100 / 150–250 recommendation is still reasonable *for that layer specifically*).
- Ticket/interaction generation logic — refactor so it routes through (or faithfully mirrors) the real service-layer invariants (audit-log side effects, SLA-start side effects) instead of raw inserts, so every downstream consumer sees one internally self-consistent world.

### 4.3 Replace
- The static, single-snapshot-in-time generation model — replaced by a genuinely temporal approach (simulated sweep replay, or a real running instance with its own scheduler — a choice for the Synthetic World Specification, §6).
- The blanket "RBAC/notifications/audit are not needed" exclusion — replaced by explicit, scoped inclusion per §1's table.

### 4.4 Remain untouched
- The real application code (`unified-backend/`, `shared_models/`) — this entire effort is, and must remain, read-only against it. Nothing here proposes changing production code or schema.
- The already-completed `RCM_APPLICATION_KNOWLEDGE_BASE.md` — it is the ground truth this reconciliation is measured against, not something to be revised as part of this exercise.

---

## 5. Proposed Future Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│  APPLICATION                                                        │
│  unified-backend/ + shared_models/ — the real, running product.     │
│  Source of truth for schema, business rules, and behavior.          │
└───────────────────────────────┬───────────────────────────────────────┘
                                 │ schema + invariants (read-only reference)
                                 ▼
┌─────────────────────────────────────────────────────────────────────┐
│  SYNTHETIC OPERATIONAL WORLD                                         │
│  An isolated, seeded/simulated instance conforming to the same       │
│  schema and invariants — users, roles, clients, tickets,             │
│  interactions, SLA clocks, escalations, notifications, audit logs.   │
│  Never the real Neon prod/dev database (see production doc §"Deploy- │
│  ment" incident history — an isolated Neon branch or local Postgres).│
└───────────────────────────────┬───────────────────────────────────────┘
                                 │ versioned export/snapshot
                                 ▼
┌─────────────────────────────────────────────────────────────────────┐
│  SHARED DATASET                                                      │
│  The canonical, versioned rows every downstream layer reads from —   │
│  so Benchmark, AI Recommendation, and Future Automation all work     │
│  off one consistent world instead of separately-generated fixtures.  │
└───────┬─────────────────────────────┬───────────────────────┬─────────┘
        │                             │                       │
        ▼                             ▼                       ▼
┌───────────────┐           ┌───────────────────┐   ┌───────────────────────┐
│ BENCHMARK      │           │ AI RECOMMENDATION  │   │ FUTURE AUTOMATION      │
│ LAYER          │◄──feeds───┤ LAYER              │   │ PROJECTS               │
│ eval queries,  │  labels   │ matching algorithm,│   │ workload-based         │
│ difficulty     │           │ scoring against    │   │ assignment ranking,    │
│ tiers,         │           │ the Benchmark Layer │   │ auto-close, SLA        │
│ should_match   │           │                     │   │ digests, schema-drift  │
│ ground truth   │           │                     │   │ checks, etc.           │
└───────┬────────┘           └──────────┬──────────┘   └────────────┬───────────┘
        │                               │                            │
        └───────────────┬───────────────┴────────────────────────────┘
                         ▼
              ┌───────────────────────┐
              │  METADATA LAYER         │
              │  (cross-cuts everything  │
              │  above — see below)      │
              └───────────────────────┘
```

### Layer responsibilities and data flow

- **Application** — the real product. Never modified by this effort; the sole authority on schema shape and business-rule behavior. Everything below must conform to it, not the other way around.
- **Synthetic Operational World** — a seeded (and ideally *behaviorally simulated*, not just row-inserted — see §2.4) isolated instance of the same schema: Users/Roles/Clients/Tickets/Interactions/SLA clocks/Escalations/Notifications/Audit logs, internally consistent with real invariants. This is the concrete realization of the Production Operational Layer from §3.2. Ideally generated *by driving the real service layer* (or a faithful simulation of it) rather than hand-crafted inserts, so temporal SLA/escalation/notification behavior is authentic rather than merely plausible-looking.
- **Shared Dataset** — a canonical, versioned export/snapshot of the Synthetic Operational World's state (a point in time, or a time range). The single thing every downstream layer reads from, so they never drift into mutually-incompatible fixtures. Read-only from every downstream layer's perspective — nothing below writes back into it.
- **Benchmark Layer** — the Research Layer from §3.1, built strictly on top of the Shared Dataset: eval queries, difficulty tiers, `should_match` labels. Consumes the Shared Dataset; produces labels *about* it; never mutates it.
- **AI Recommendation Layer** — the actual ticket-recommendation feature under development. Consumes the Shared Dataset (as realistic input) and the Benchmark Layer (as its scoring harness) to develop and evaluate a matching algorithm. This is one specific consumer of the architecture, not the only one — a distinction the original benchmark-first framing didn't need to make, but a production-aligned one does.
- **Future Automation Projects** — other automation ideas already discussed for this application (workload-based assignment ranking — already design-scoped in the Application's own roadmap per `RCM_APPLICATION_KNOWLEDGE_BASE.md` §20 — plus auto-close, SLA compliance digests, schema-drift checks, and others). These consume the same Shared Dataset for their own development/testing. This is precisely why the Synthetic Operational World must be genuinely production-aligned rather than narrowly cut for the recommendation feature alone — it's meant to be reused, not rebuilt per project.
- **Metadata Layer** — cross-cuts every layer above rather than sitting strictly "after" the Shared Dataset: generation parameters and seeds (for reproducibility), the exact application-schema version a given Shared Dataset snapshot was generated against, and explicit annotations of which known production gaps (production doc §19 — e.g., the CRITICAL-priority enforcement gap, the escalation-freeze bypass gaps) were modeled *as-is* versus modeled *as-fixed* in a given snapshot. Every other layer needs to be able to ask the Metadata Layer "what exactly am I looking at, and does it match the application version I care about" — without it, Shared Dataset snapshots silently rot as the real Application evolves.

---

## 6. Implementation Roadmap

**Roadmap only — no implementation begins here.** Recommended order for the remaining design documents, with the reasoning for that order:

1. **Synthetic World Specification** — defines exactly what the Synthetic Operational World contains: which tables from §1's table are populated at what richness, the chosen temporal model (static snapshot vs. simulated sweep-replay vs. a live running instance), and — critically — a per-item decision on which of the confirmed production gaps (production doc §19.2) get modeled as-is vs. as-fixed. This has to come first because every later document depends on this scope decision.
2. **Schema Mapping** — the concrete field-by-field mapping from this report's §1 categorization into actual DDL/ORM models — including the explicit decision of whether the Synthetic World literally reuses `shared_models`/`unified-backend` models directly (a real isolated instance of the same app) or a distilled standalone schema. Comes second because it operationalizes whatever scope §1 (Synthetic World Specification) settled on.
3. **Generator Architecture** — how content actually gets produced: service-layer-driven simulation vs. direct-insert batch generation vs. a hybrid; how the SLA-sweep/escalation temporal behavior gets simulated concretely; how RCM-domain content (glossary-grounded threads) gets authored (templated vs. LLM-generated vs. hybrid). Depends on both prior documents being settled.
4. **Metadata & Versioning Design** — how generation runs are tracked for reproducibility, how a Shared Dataset snapshot gets tagged against the exact application-schema version it targets, and how known-gap modeling choices (from step 1) get recorded so downstream consumers can trust what they're looking at. Comes after Generator Architecture since it needs to know what the generator actually produces in order to describe how to version it.
5. **Benchmark Design** — the eval query set methodology, difficulty-tier construction, and labeling process, now explicitly scoped as a layer built *on top of* the Shared Dataset (per §5) rather than being the whole project, as the original benchmark-first framing implied.
6. **AI Architecture** — the actual recommendation algorithm design (retrieval approach, candidate scoring, model choice) — deliberately after the Benchmark Design, since the algorithm should be designed against a settled evaluation methodology, not the other way around.
7. **Technology Selection** — concrete tool/technology choices (e.g., pgvector vs. an external vector store, an LLM provider for content generation, orchestration tooling for the generator). Deliberately placed late so tool choice follows settled design rather than driving it.
8. **Implementation** — actual build, last, once every design decision above has been made explicitly rather than discovered mid-build.
