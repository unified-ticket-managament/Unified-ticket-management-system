# Workflow Documentation Standard

Every document under [03-business-workflows](README.md) follows this structure. Sections that genuinely don't apply to a given workflow are kept but marked "N/A" rather than omitted, so the template stays predictable to skim.

1. **Purpose** — what this workflow accomplishes and why it exists
2. **Trigger** — the specific event that starts it (an API call, a scheduled tick, an inbound webhook)
3. **Actors** — who/what participates (roles, the system itself, external services)
4. **Preconditions** — what must already be true for this workflow to run
5. **High-Level Flow** — a short, skimmable step list or Mermaid diagram
6. **Detailed Workflow** — the actual step-by-step mechanics, referencing real functions/services
7. **Business Rules** — the "why," stated as a rule a business stakeholder would recognize
8. **Decision Points** — every branch and what determines which way it goes
9. **Database Changes** — which tables/columns are written, and what the write means
10. **APIs Involved** — the endpoint(s) that trigger or are involved in this workflow
11. **Services / Components Involved** — the real service classes/functions
12. **External Integrations** — Graph, SMTP, storage, etc., if applicable
13. **Notifications** — what fires, to whom, and whether it's also emailed
14. **Audit Events** — which audit system(s) record this, and which event type(s)
15. **Failure Scenarios** — what can go wrong and what happens when it does
16. **Edge Cases** — the non-obvious paths (already-ticketed mail, concurrent claims, etc.)
17. **Postconditions** — what's guaranteed true once the workflow completes
18. **Relevant Source Files** — exact repo-relative paths
19. **Example Scenario** — one concrete walk-through with realistic values

Business rules are stated as **rule, then implementation** — e.g. "SLA starts when the client's initial communication is received" (the rule) is followed by "initialized during ticket/interaction creation by `SLAService`" (the implementation) — so both a technical and a business reader get value from the same paragraph.
