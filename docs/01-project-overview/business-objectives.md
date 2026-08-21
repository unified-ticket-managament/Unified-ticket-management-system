# Business Objectives

These objectives are inferred from what the system actually enforces and automates — not from a separate product-requirements document (none was found in the repository). Where an objective is explicitly confirmed by a dated engineering note in root `CLAUDE.md` (e.g. a feature built "from an explicit business spec"), that's called out.

## 1. Never lose a client communication

Every inbound email is captured, deduplicated by `message_id`, matched to a client, and threaded onto the correct conversation — whether or not a ticket exists yet. Unmatched mail to a shared mailbox routes to a fallback (Site Lead) rather than being silently dropped.

## 2. Make response-time commitments visible and enforceable, not just aspirational

Two independent SLA clocks (First Response, Resolution) with configurable per-priority targets, live-editable by a Super Admin without a code deployment (SLA Timing Matrix). Four graduated warning thresholds surface risk before a breach, not just after.

## 3. Escalate ownership automatically when a commitment is at risk — without losing accountability

The escalation workflow auto-creates on a breach, starts at the level *above* whoever currently owns the ticket (never re-notifying the person already failing to act), and auto-advances through Team Lead → Account Manager → Site Lead if no one acknowledges within a configurable ack window. A permanent, escalation-only CRITICAL priority tier makes an escalated ticket visibly distinct company-wide.

## 4. Give supervisors reporting/assignment flexibility independent of the RBAC role ladder

The Organization Structure feature (confirmed built from "an explicit business spec") deliberately separates three relationships that could easily have been collapsed into one: the real reporting line, an additional Reporting-Manager HR responsibility layered onto an Account Manager, and a company-wide ticket-assignment capability that isn't limited by reporting hierarchy at all.

## 5. Fine-grained, auditable access control beyond static roles

Per-user permission overrides (including ticket-scoped grants), a request/approval workflow addressed to a specific person, and an audit trail across both domains — built specifically because a flat six-role system doesn't cover every real access-granting scenario an organization needs (e.g. "let this one Staff member edit this one teammate's ticket").

## 6. Keep the product feeling like one application, not two

The ticket workspace is embedded directly into the RBAC shell (not linked out to a separate app), with a unified design system and role-based landing pages — a deliberate, confirmed design goal from the consolidation work.

## Not confirmed

No formal business-requirements or product-charter document exists in the repository to cross-check these objectives against an original mandate — the above is derived entirely from what the shipped system actually does and enforces.
