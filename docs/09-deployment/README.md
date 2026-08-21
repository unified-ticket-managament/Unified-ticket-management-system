# Deployment

**This section required reconciling three sources that disagree with each other** — `DEPLOYMENT.md` (root), `render.yaml` (root), and `.github/workflows/deploy.yml` — and the actual, current-as-of-this-pass file contents win over any prose description, per this documentation set's own source-of-truth rule.

- [environments.md](environments.md) — which environments exist, and the confirmed ambiguity about which is "real" production
- [infrastructure.md](infrastructure.md) — Neon, Supabase, MinIO (local), Render, EC2
- [deployment-architecture.md](deployment-architecture.md) — the two coexisting deployment paths, side by side
- [deployment-process.md](deployment-process.md) — the actual, step-by-step build→deploy→restart→verify sequence for each path
- [database-migrations.md](database-migrations.md) — how migrations run as part of deployment
- [environment-configuration.md](environment-configuration.md) — where each path's config lives
- [rollback.md](rollback.md) — how to roll back, for each path
- [health-checks.md](health-checks.md) — `/health`, and the port-mismatch gotcha between the two paths

## The one fact every other document in this section depends on

`render.yaml` currently defines **exactly 2 services** (`unified-backend`, `unified-frontend`) — not the 4-service topology (`rbac-backend`/`rbac-frontend`/`ticketing-backend`/`ticketing-frontend`) that `DEPLOYMENT.md` still walks through step by step. Meanwhile, `.github/workflows/deploy.yml` — the **only** workflow that fires automatically, on every push to `main` — deploys to an **EC2 host via SSH**, entirely independent of Render. **Confirm with whoever manages production infrastructure which of these (or both) is the live environment before following either runbook.**
