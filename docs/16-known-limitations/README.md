# Known Limitations

This section documents gaps in the **current, running system** — not missing features that were never intended. Every entry below is either confirmed directly from code/config, or copied from the project's own dated engineering log (root `CLAUDE.md`) where a limitation was explicitly identified and deliberately left unresolved.

Limitations are split into four files:

- [functional-limitations.md](functional-limitations.md) — things the product doesn't do, by design or by gap
- [technical-limitations.md](technical-limitations.md) — architectural constraints (scaling, consistency, test isolation)
- [performance-limitations.md](performance-limitations.md) — throughput/latency ceilings and their causes
- [integration-limitations.md](integration-limitations.md) — external-system boundaries (Graph, SMTP, storage)

See also [17-roadmap](../17-roadmap/README.md) for which of these are planned to be addressed, and [15-architecture-decisions](../15-architecture-decisions/README.md) for the reasoning behind the deliberate ones.

## How to read an entry

Each limitation states:
- **Limitation** — what doesn't work / isn't covered
- **Impact** — who/what is affected
- **Why It Exists** — the tradeoff or constraint that produced it
- **Current Workaround** (if any)
- **Is It Planned?** — yes/no/unknown, with a pointer into the roadmap if yes
