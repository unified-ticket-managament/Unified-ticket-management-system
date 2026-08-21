# Roadmap & Backlog

**Everything in this section is sourced from actual code comments, dated engineering notes in root `CLAUDE.md`, disabled/partial functionality, and known technical debt already documented elsewhere in this doc set — nothing here is invented.** Where root `CLAUDE.md` explicitly labels something "PLANNED" or a "known limitation," that label is carried through faithfully.

- [v1-production-scope.md](v1-production-scope.md) — what's in the current production release
- [v1.1-enhancements.md](v1.1-enhancements.md) — small, likely-near-term improvements implied by known gaps
- [v2-roadmap.md](v2-roadmap.md) — the one explicitly-designed future feature (workload-based assignment)
- [technical-debt.md](technical-debt.md) — debt items with a clear owner/cause
- [performance-improvements.md](performance-improvements.md) — confirmed opportunities, distinct from debt
- [security-enhancements.md](security-enhancements.md) — the RBAC-enforcement gap and related items
- [ai-automation-roadmap.md](ai-automation-roadmap.md) — the two-phase workload-scoring design, phase 2 unstarted
- [backlog.md](backlog.md) — everything else, in one structured list

## How to read status labels

- **Implemented** — real, shipped code.
- **Partially Implemented** — the plumbing exists, the full feature doesn't (e.g. Reporting Managers).
- **Planned** — a real design note exists, but no code.
- **Deferred** — explicitly decided against for now, with a stated reason.
- **Technical Debt** — works today, but with a known, accepted cost.
- **Potential Future Enhancement** — a plausible idea with no design work done at all.
