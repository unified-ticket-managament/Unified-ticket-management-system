# Repository Setup

```bash
git clone https://github.com/unified-ticket-managament/Unified-ticket-management-system.git
cd Unified-ticket-management-system
```

## Orienting yourself

See [05-technical-architecture/repository-structure.md](../05-technical-architecture/repository-structure.md) for the full directory map. The short version:

- **`unified-backend/`** — the only backend; everything runs from here.
- **`unified-frontend/`** — the only frontend you need to run for full functionality (embeds the ticket workspace).
- **`shared_models/`** — installed automatically as a local editable dependency by `unified-backend`'s `pip install -r requirements.txt` (`-e ../shared_models` is in `requirements.txt`) — you don't need to `pip install` it separately.
- **`ticketing-service/`** — empty as of 2026-08-21 (its last remnant, a stale pre-built frontend bundle, was deleted in the same commit that added client filters/the OTP classifier). Nothing to do here; not part of current deployment.
- **`CLAUDE.md`** (root) and **`unified-frontend/CLAUDE.md`** — extremely detailed, dated engineering logs. Read them for historical context and known gotchas, but cross-check anything load-bearing against the actual code — both files contain some confirmed-stale sections (see [16-known-limitations](../16-known-limitations/README.md)).
- **`DEPLOYMENT.md`** (root) — **stale**, describes a retired 4-service topology. Don't follow it. See [09-deployment](../09-deployment/README.md) for the current, reconciled picture.

## Don't start here for setup steps

`unified-frontend/docs/{ARCHITECTURE,API,DEPLOYMENT}.md` are explicitly flagged (in `unified-frontend/CLAUDE.md`'s own Known Issues) as describing an earlier/aspirational design that has drifted from the actual implementation. Use this `docs/` tree (the one you're reading) instead.
