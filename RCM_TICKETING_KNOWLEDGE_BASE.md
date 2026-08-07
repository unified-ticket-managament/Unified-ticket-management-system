       # RCM Ticketing — Application & Domain Knowledge Base (for Synthetic Data Generation)

       **Purpose of this document**: a self-contained business/domain brief to generate a *realistic* synthetic ticket corpus + evaluation query set for the AI Ticket Recommendation project (see `ticket-recommendation.pdf`'s benchmark notes). It complements — does not replace — `ML_TICKETING_SCHEMA_REFERENCE.md`, which is the authoritative, code-verified source for exact table/column/enum definitions. Where the two overlap, this document summarizes; `ML_TICKETING_SCHEMA_REFERENCE.md` is the source of truth for anything schema-shaped (types, nullability, FKs, indexes).

       **No dataset is generated in this document** — this is the knowledge brief a generator will be built from next.

       ---

       ## 1. What this application is

       A ticket management system for **Revenue Cycle Management (RCM) support** — the internal team of a medical billing company handles operational email traffic from its client companies (physician practices, clinics, billing departments) about claims, payments, authorizations, and patient accounts. Every client company has one shared inbox address; any number of people at that client can email in, and all of it lands in one company-wide mail pool before being triaged into tickets.

       The product is two things at once:
       - A **mailbox-to-ticket triage tool**: inbound email → shared pool → agent decides "reply and archive" (no ticket needed) vs. "this needs operational tracking" (create a ticket, or attach to an existing one).
       - A **ticket work-tracking tool** once a ticket exists: assignment, replies, internal notes, attachments, status/priority changes, SLA clocks, and an internal escalation ownership chain when things run late.

       The **AI Ticket Recommendation** project sits at exactly one seam in this flow: when a brand-new, thread-unlinked email arrives, help the triaging agent answer "does this actually belong to one of our existing active tickets?" before they decide to create a new one. ("Active" — not literally `OPEN` — is a deliberate, justified choice; see §6's "Candidate pool for AI ticket recommendation" subsection.) See §7 for exactly where this fits in the real (not the simplified PDF) workflow.

       ---

       ## 2. RCM domain terminology (glossary)

       This system's ticket categories and conversation content are medical-billing-specific. A synthetic generator needs this vocabulary to produce content that reads as authentic rather than generic "customer support."

       | Term | Meaning |
       |---|---|
       | **RCM (Revenue Cycle Management)** | The end-to-end process of getting a healthcare provider paid: registration/eligibility → charge capture → claim submission → payment posting → denial management → AR follow-up. |
       | **Claim** | A formal request submitted to a payer (insurance company) for payment for services rendered. |
       | **Payer** | The insurance company or government program (Medicare, Medicaid, commercial plans) responsible for paying a claim. |
       | **Clearinghouse** | An intermediary that transmits claims electronically from provider to payer, scrubbing/validating them first. |
       | **EOB (Explanation of Benefits)** | A payer statement explaining what was paid, denied, and why. |
       | **ERA (Electronic Remittance Advice)** | The machine-readable electronic equivalent of an EOB. |
       | **Denial** | A payer's refusal to pay a claim, accompanied by a reason code. |
       | **CARC / RARC** | Claim/Remittance Adjustment Reason Codes — standardized codes explaining a denial or adjustment (e.g., CO-16 "missing information," CO-97 "benefit bundled into another service," CO-29 "timely filing limit expired"). |
       | **Appeal** | A formal request to reconsider a denied claim. |
       | **Resubmission** | Re-sending a corrected claim after a denial or rejection. |
       | **Prior Authorization (PA / Auth)** | Payer approval required *before* a service is performed, to guarantee payment. Can be denied, expire, or require a "retro" (after-the-fact) request. |
       | **Eligibility Verification** | Confirming a patient's insurance coverage/benefits before or at time of service. |
       | **Coordination of Benefits (COB)** | Determining which of a patient's multiple payers is primary vs. secondary. |
       | **Charge Entry** | Entering billable services (CPT/HCPCS procedure codes) with diagnosis codes (ICD-10) into the billing system to generate a claim. |
       | **CPT / HCPCS code** | Procedure/service code on a claim. |
       | **ICD-10 code** | Diagnosis code on a claim. |
       | **Modifier** | A two-character code appended to a CPT code altering its meaning (e.g., bilateral procedure, multiple procedures). |
       | **NPI (National Provider Identifier)** | Unique ID for a healthcare provider/organization. |
       | **Superbill / Encounter Form** | The source document listing diagnoses/procedures for a visit, used to generate a claim. |
       | **Timely Filing Limit** | The payer-imposed deadline (often 90–180 days) to submit or appeal a claim. |
       | **Accounts Receivable (AR)** | Unpaid claims/balances owed to the provider. "AR follow-up" = working aged claims until they're paid or resolved. |
       | **Aging Bucket** | AR grouped by how long it's been outstanding (0–30, 31–60, 61–90, 90+ days) — older buckets are higher urgency. |
       | **Payment Posting** | Recording payments/adjustments from an EOB/ERA into the billing system against the correct claim/patient account. |
       | **Contractual Adjustment / Write-off** | The portion of a charge the provider agrees not to collect (payer contract rate, or bad debt). |
       | **Patient Responsibility** | The portion of a bill the patient (not the payer) owes — copay, deductible, coinsurance. |
       | **Credentialing** | Verifying a provider's qualifications with a payer so they can bill that payer at all (occasionally adjacent to PA/Eligibility tickets). |

       ---

       ## 3. Roles & organization (who generates/handles this content)

       Real RBAC roles (`shared_models.models.Role`, seeded, no rank column — hierarchy is app-code-only):

       | Role | Ticketing responsibility |
       |---|---|
       | **Super Admin** | Unrestricted oversight; not typically a ticket actor in synthetic conversation content. |
       | **Site Lead** | Company-wide oversight, global inbox, terminal escalation level, unmatched-mail catch-all. |
       | **Account Manager** | Owns a set of client companies (`clients.account_manager_id`); this is the actual **client-facing correspondent** in most ticket threads — the email address clients see replies come from. Escalation level 2. |
       | **Team Lead** | Operational head of one work-specialization category (Eligibility/AR/Claims/etc.); supervises that category's Staff. Escalation level 1 (the usual starting point). |
       | **Staff** | Does the hands-on category-scoped work (works claims, posts payments, verifies eligibility, etc.) — the most common `agent_id`/reply-author for routine ticket work. |
       | **Viewer** | Client-facing role, not a ticket actor. |

       **A `Client` is a company, not a person** (`unified-backend/app/ticketing/models/client.py`) — e.g. "Lakeside Medical Billing LLC," not an individual patient. Any number of people at that client company can email in from the client's own domain; all route to the same `Client` row via `inbox_email`, and to one owning Account Manager. **A ticket's "customer" for the purposes of this ML project is therefore the Client company, not an individual patient** — "same customer disambiguation" (§9) means "same client company, multiple open tickets," not "same individual person."

       ---

       ## 4. Ticket categories — the real classification axis

       `CategoryName` (`shared_models.models.category.py`, native Postgres enum, 7 fixed values — **this is the only classification axis on a ticket**; there is no separate "issue type" field in the schema). Each category maps to one RCM business function and has characteristic issue types worth generating realistic scenarios for:

       | Category (enum value) | RCM function | Characteristic issue types (for synthetic scenarios) |
       |---|---|---|
       | **Eligibility** | Verifying patient insurance coverage/benefits | Coverage terminated/inactive, wrong plan on file, COB (primary/secondary) mismatch, benefits verification delay, plan requires referral not on file |
       | **Patient Calling** | Patient-facing billing communication | Balance/statement disputes, payment plan requests, patient demographic/address corrections, complaint about a collections call |
       | **AR (Accounts Receivable)** | Following up on unpaid/aged claims | Aged claim with no payer response, appeal status check, claim stuck "in process" past normal turnaround, aging-bucket escalation |
       | **Payment Posting** | Recording payments from EOBs/ERAs | Payment posted to wrong account/claim, EOB doesn't match expected amount, missing/unposted ERA, refund request from overpayment |
       | **PA (Prior Authorization)** | Getting payer approval before service | Auth denied, auth expired before service rendered, missing clinical documentation for auth request, need retro-authorization, wrong CPT code on auth |
       | **Charge Entry** | Entering billable services into the system | Coding error (wrong CPT/ICD-10), missing modifier, charge never entered from superbill, duplicate charge entered |
       | **Claims** | Submitting and resolving claims | Claim denied (with a CARC-style reason), claim rejected at clearinghouse (pre-payer), needs resubmission after correction, needs formal appeal, missing NPI/provider info |

       **Known schema gap to respect, not "fix," in synthetic data**: `Ticket.ticket_type` is a plain `String(50)` with no FK to `categories` — nothing stops an arbitrary string. Generate `ticket_type` from the 7 values above anyway, for realism, matching `ML_TICKETING_SCHEMA_REFERENCE.md`'s own guidance.

       ---

       ## 5. Core entities & relationships (condensed — see `ML_TICKETING_SCHEMA_REFERENCE.md` §1–2 for exact columns)

       - **User** — an internal team member; holds one Role, optionally one Category (Staff/Team Lead only), optional `manager_id`/`teamlead_id` reporting lines.
       - **Client** — a client company; one `inbox_email`, one owning Account Manager.
       - **Interaction** — the atomic timeline unit: an inbound email, an outbound reply, an internal note, or an attachment event. **Always created before any ticket** — a ticket cannot exist without a founding Interaction (there is no "blank ticket" creation path in this codebase). Threads via `parent_interaction_id`/`conversation_id`/`message_id`/`in_reply_to_message_id`/`references`.
       - **Ticket** — the work item an Interaction gets promoted into. Belongs to a Client (`client_company_id`), optionally assigned to a User (`agent_id`), has a category (`ticket_type`), status, priority.
       - **Attachment** — belongs to an Interaction only (never directly to a Ticket).
       - **ResolutionSLA** — 1:1 clock per Ticket, whole-ticket-lifetime, pauses while `WAITING_FOR_CLIENT`.
       - **FirstResponseSLA** — 1:1 clock per thread-root Interaction (not the ticket) — measures triage speed, completes the moment the item is archived/replied/ticketed.
       - **TicketEscalation** / **EscalationHandlingSLA** — internal ownership hand-off chain layered on top of (never mutating) ResolutionSLA, for when a ticket runs late.
       - **TicketRelation** — a plain, symmetric "these are related" link an agent can draw manually between two tickets — architecturally the closest existing analog to what a recommendation system produces, worth knowing about even though it's manual today.

       ```
       Client (company) ──< Interaction (email/reply/note) >── Ticket ──< ResolutionSLA (1:1)
                                   │                              │
                            (thread root) ──< FirstResponseSLA    ├──< TicketEscalation ──< EscalationHandlingSLA
                                   │                              │
                            Attachment                     TicketRelation (self-link)
       ```

       ---

       ## 6. Ticket status lifecycle

       `TicketStatus` (`ticket_status_enum`): **`OPEN → IN_PROGRESS → PENDING → WAITING_FOR_CLIENT → RESOLVED → CLOSED`** (not a strict linear path — a ticket can move between several of these more than once before closing; `WAITING_FOR_CLIENT` specifically pauses the Resolution SLA clock and resumes it on the next inbound reply).

       - A new ticket always starts at **`OPEN`** (system-set, never chosen).
       - **`RESOLVED`** does **not** stop the Resolution SLA clock — only **`CLOSED`** does, and only a supervisor can close a ticket (`ticket:close_ticket`, bypassed unconditionally only by Site Lead/Super Admin). This models the real business requirement that an agent proposing a fix isn't the same as a supervisor verifying and closing it.
       - **`CLOSED`** is terminal for every action except **Reopen** (`ticket:reopen`) — a closed ticket blocks replies, notes, priority changes, transfers, attachment uploads until reopened.
       - **`current_priority`**: `LOW / MEDIUM / HIGH` are the only manually-selectable tiers (agent picks at ticket creation or via Change Priority). **`CRITICAL` is never manually selectable** — it is set exactly once, automatically, the moment a ticket's internal escalation workflow creates its first escalation, and never reverts. **A synthetic historical corpus should essentially never contain a `CRITICAL`-priority ticket unless you are deliberately simulating an already-escalated ticket** — for the recommendation-benchmark's purposes, treat `CRITICAL` as out of scope for routine synthetic generation.

       **Internal escalation** (separate concept from priority/status): if a ticket's Resolution SLA breaches badly enough, or a supervisor manually escalates it, ownership hands off up a `TEAM_LEAD → MANAGER → SITE_LEAD` chain (independent of, and never touching, the Resolution SLA clock's own timing). This is operational/metadata for a recommendation system, not retrieval content — see `ML_TICKETING_SCHEMA_REFERENCE.md` §8's classification table — but is realistic to include as sparse metadata (e.g., a small fraction of synthetic tickets flagged `is_escalated`).

### Candidate pool for AI ticket recommendation — which statuses are eligible

The PDF's own framing ("does this belong to an existing **OPEN** ticket?") assumes a binary OPEN/CLOSED model. Against the real 6-value enum, restricting the candidate pool to literally `current_status == 'OPEN'` is wrong — it excludes exactly the tickets most likely to receive a genuine follow-up:

- **`IN_PROGRESS`** — a client sending more info via a new email while an agent is actively working the issue is one of the most common real scenarios; excluding it causes duplicate tickets on work already in flight.
- **`PENDING`** — an ordinary active/queued state with no special semantics beyond not being `WAITING_FOR_CLIENT`; no reason to exclude it.
- **`WAITING_FOR_CLIENT`** — **the single most important status to include, not exclude.** This status exists specifically because the team is waiting on the client to send something back (documentation, confirmation, missing info) — it's the reason the Resolution SLA clock is paused. If that reply arrives as a *new*, thread-unlinked email instead of an in-thread reply (very common — forwarded from a colleague, or composed fresh), the deterministic thread-matcher (`OpenEmailService._recommend_ticket`, §7) cannot catch it. This is exactly the gap the AI recommendation project exists to close; excluding this status would gut its highest-value case.
- **`RESOLVED`** — confirmed by the codebase's own model, not just judgment: `ResolutionSLA`'s docstring is explicit that entering `RESOLVED` does **not** complete the Resolution SLA clock — only `CLOSED` does. The system already treats `RESOLVED` as "agent believes it's fixed, pending supervisor verification," not terminal. A client's follow-up at this point should reattach here, not spawn an orphaned duplicate while the RESOLVED ticket gets closed by a supervisor who never sees the follow-up.
- **`CLOSED`** — the one genuinely excluded status. It's the only state gated by a dedicated, permissioned Reopen action (`ticket:reopen`). Two reasons converge on excluding it specifically: (1) the system's own invariant already draws the terminal line at `CLOSED`, not `RESOLVED`; (2) asymmetric failure cost — a missed match just costs a duplicate ticket (cheap to clean up), while a false-positive attach onto a `CLOSED` ticket either silently bypasses the Reopen permission gate or leaves a client message buried in a ticket no longer in anyone's active queue (a real compliance risk given timely-filing deadlines).

**Correct rule: candidate pool = `current_status != 'CLOSED'`** (`OPEN, IN_PROGRESS, PENDING, WAITING_FOR_CLIENT, RESOLVED`), scoped by `client_company_id` as established in §10. (Downstream integration note, not an eligibility question: attaching a new email to a `WAITING_FOR_CLIENT` ticket should trigger the same `resume_resolution_clock` behavior an in-thread reply already gets.)

       ---

       ## 7. End-to-end business workflow (real system, not the simplified PDF flowchart)

       The PDF's flowchart ("Customer sends Email → Account Manager → operational work required? → Create Ticket or Attach Existing → future emails: reply-in-thread [auto] vs. new independent email [AI Retrieval]") is directionally right but glosses over the real mechanics. Here is the actual pipeline (`ML_TICKETING_SCHEMA_REFERENCE.md` §7, condensed):

       1. **Inbound email arrives** at the client company's shared mailbox (Microsoft Graph). Duplicate-checked by `message_id`.
       2. **Client resolution** — sender/recipient address matched against `clients.inbox_email`. Unmatched mail routes to Site Lead rather than being rejected.
       3. **Deterministic thread match** — `conversation_id` → `in_reply_to_message_id` → `references`, first hit wins, walked to the true root. **This is the existing, non-ML mechanism that already solves "is this a reply in an existing thread."** If it matches an already-ticketed thread, the email is auto-attached and the pipeline stops — no agent decision needed.
       4. If no thread match, the email becomes a **new pool item** (`Interaction` with `ticket_id=NULL`, `status=PENDING`) sitting in the shared Mail inbox. `FirstResponseSLA` starts here.
       5. **This is where the AI Ticket Recommendation feature fires** — for a pool item with no deterministic thread match, the AI should ask: does this new independent email actually describe an issue that matches one of the client's (or company's) existing **active (non-`CLOSED`)** tickets, even though it's not literally the same email thread? (E.g., a client's billing person emails a brand-new message about the same denied claim they already opened a ticket for last week, without replying to the original thread.)
       6. **Agent decides** — reply/archive (no ticket needed), attach to an AI-suggested or manually-searched existing ticket, or **Create Ticket** (`title`, `ticket_type`, optional `current_priority`/`agent_id`). Creating a ticket also drags every other interaction already filed under that same thread onto the new ticket in one batch.
       7. Ticket now has its own `ResolutionSLA`; `FirstResponseSLA` completes (`reason="TICKET_CREATED"`).
       8. **Ticket work happens**: replies, internal notes, attachments, status/priority changes, possibly transfer between agents, possibly escalation if it runs late.
       9. Ticket reaches `RESOLVED` (agent-proposed) then `CLOSED` (supervisor-verified) — or a client's continued replies keep it `IN_PROGRESS`/`WAITING_FOR_CLIENT` for a while first.

       **Existing prior art, not to be confused with the new AI feature**: `OpenEmailService._recommend_ticket` (`unified-backend/app/ticketing/services/open_email_service.py`) already does a *deterministic, non-ML* "attach to existing ticket" suggestion — but only by re-checking exact thread-root/reply/message-id/header matches as a safety net for threads that should have auto-matched at intake but didn't. It explicitly does **not** do subject/content similarity (the code comment notes there's no human-readable ticket number to parse from a subject line — everything is a UUID). **The AI Recommendation project is a strict superset of what this covers**: it targets the case this heuristic cannot — a genuinely new, unlinked email thread that's semantically about an existing active ticket's issue, not a threading/header match at all.

       ---

       ## 8. Conversation / message-intent patterns (for realistic multi-turn threads)

       Adapting the PDF's "Message Intents" to real RCM content — a realistic synthetic ticket thread should mix several of these across its interactions:

       | Intent | Example (Claims category) |
       |---|---|
       | **Initial Request** | "Claim #48213 for patient J.D. was denied for CO-16 (missing information). Can you tell us what's missing so we can resubmit?" |
       | **Documentation Provided** | "Attached is the corrected superbill with the missing modifier. Please resubmit at your earliest convenience." |
       | **Follow-up / Status Check** | "Just checking in — any update on claim #48213's resubmission?" |
       | **Informational Message** | "FYI, this payer has said they're experiencing system delays processing all claims this month." |
       | **Urgency / Escalation** | "We're now past the 180-day timely filing limit on this one — please treat as urgent." |
       | **Thank You / Close-out** | "Great, thank you — claim shows paid now. Appreciate the help!" |

       A realistic thread is typically 3–8 messages alternating INBOUND (client) / OUTBOUND (agent reply) direction, occasionally with an INTERNAL_NOTE (agent-only, never client-visible) mixed in for internal handoff context.

       ---

       ## 9. Difficulty taxonomy for the eventual evaluation query set

       Directly reusable from the PDF's own design (already a strong choice) — mapped onto real RCM scenarios:

       | Tier | What it tests | RCM example |
       |---|---|---|
       | **Easy** | Clear, direct match to one ticket | "Following up on claim #48213 denial — any update?" (same claim #, same subject-ish wording as the open ticket) |
       | **Moderate** | Same meaning, different wording | "Checking back on that rejected claim from last week" (no claim # repeated, but clearly the same issue) |
       | **Hard Semantic** | Vague/incomplete but still matchable | "Any update on this?" sent standalone, but from a client with exactly one recently-active OPEN ticket |
       | **Same-Customer Disambiguation** | One client, multiple OPEN tickets, must resolve to the *right* one | A client with an open Claims ticket AND an open PA ticket both gets a generic "any update?" — correct answer depends on subtler cues (recency, prior thread content) |
       | **Hard Negative** | Looks similar, but genuinely no matching ticket exists | A *new* denied claim for a *different* patient/claim number at a client that already has an unrelated open Claims ticket — must resolve to `should_match=False` |
       | **Boilerplate** | Very short, generic, low-signal | "Thanks!" / "Got it" / "Any update?" — stress-tests the no-match threshold |

       ---

       ## 10. Business rules & constraints a generator must respect

       Condensed from `ML_TICKETING_SCHEMA_REFERENCE.md` §6 and load-bearing facts — the hard invariants:

       1. **Generation order**: `Client` → founding `Interaction` (EMAIL) → `Ticket` → (optional `ResolutionSLA`/`FirstResponseSLA`). A ticket never exists without a prior interaction.
       2. **`ticket_type`** sampled from the 7 real `CategoryName` values (§4), even though nothing enforces it at the DB level.
       3. **`current_priority`** sampled from `LOW/MEDIUM/HIGH` only for routine synthetic tickets — `CRITICAL` is escalation-only (see §6).
       4. **`current_status`** starts `OPEN`; for the recommendation benchmark's purposes, the candidate/target pool is every status except `CLOSED` — see §6's "Candidate pool for AI ticket recommendation" subsection for the full justification (§11's open question #1 is now resolved by that decision).
       5. **One client company, many senders** — a realistic client should have 2–5 distinct plausible sender names/addresses at the same domain (different billing staff at that practice emailing in), not one single sender per client.
       6. **A ticket's title** is realistically close to (often identical to, sometimes a lightly cleaned-up version of) its founding email's subject line — an agent usually copies or lightly edits it rather than writing something unrelated.
       7. **No real PHI or real company/payer identities** — synthetic client names, patient references (use initials or clearly-fake full names, never real people), payer names should read as generic/plausible ("a major commercial payer," fictional plan names) rather than reproducing a real insurer's actual claims-processing quirks in a way that could be mistaken for real data.
       8. **Attachments belong to interactions, not tickets** — if modeling attachment-bearing scenarios (e.g. "Documentation Provided" messages), attach at the Interaction level.

       ---

       ## 11. Assumptions to confirm before generating data (open questions)

       These are genuine decisions, not facts derivable from the codebase — flag/confirm before building the generator:

       1. ~~What does "OPEN" mean for the recommendation target set?~~ **RESOLVED**: the candidate/target pool is every status except `CLOSED` (`OPEN, IN_PROGRESS, PENDING, WAITING_FOR_CLIENT, RESOLVED`) — see §6's "Candidate pool for AI ticket recommendation" subsection for the full reasoning. `RESOLVED` is included deliberately (it's not terminal in this system — only `CLOSED` is); `CLOSED` is excluded deliberately (reopening it is a permissioned, deliberate action, not a side effect of an AI suggestion).
       2. **Scale**: how many synthetic clients, tickets per client, and messages per ticket to generate? (A prior recommendation, not yet finalized: ~15–20 clients, ~50–100 tickets total, 150–250 eval queries — small but well-curated, per standard retrieval-eval practice.)
       3. **Category/priority/status distribution weights** — no real historical distribution exists to draw from. A reasonable starting assumption: Claims/AR/Payment Posting carry the most volume in a real RCM shop (skew ticket counts toward these three), Eligibility/Patient Calling moderate, PA/Charge Entry lighter — but this is an assumption to sanity-check against whoever actually runs this business, not a derived fact.
       4. **Time span to simulate** — a single snapshot in time (all tickets "current"), or a realistic multi-month history with some tickets already closed (useful for recency-based scoring signals)?
       5. **Whether to include escalation/SLA metadata at all in v1 synthetic data** — per `ML_TICKETING_SCHEMA_REFERENCE.md` §9, this is optional and only needed if the recommendation UI will surface it as metadata (e.g., an "escalated" badge next to a suggestion).

       ---

       ## 12. Where to look for more detail

       - **Exact schema** (columns, types, enums, indexes, sample rows): `ML_TICKETING_SCHEMA_REFERENCE.md` (repo root).
       - **SLA/escalation business rules in full depth**: root `CLAUDE.md`'s "SLA & Escalation" and "CRITICAL priority" sections.
       - **RBAC/permission model**: root `CLAUDE.md`'s "RBAC permission compliance audit" section and `unified-backend/app/ticketing/services/access_control.py`.
       - **Real email intake mechanics**: `unified-backend/app/ticketing/services/open_email_service.py`, `email_service.py`, `mail_mapping_service.py`, `inbox_ticket_service.py`.
