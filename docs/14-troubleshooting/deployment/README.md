# Troubleshooting: Deployment

## Problem: `uvicorn --reload` fails with `[WinError 10013]` on Windows

**Symptoms**: Starting the backend fails with "An attempt was made to access a socket in a way forbidden by its access permissions."

**Possible Causes**: Almost always a previous backend process is still alive and already bound to port 8000 — **not** a real firewall/permissions problem despite the error text.

**How to Diagnose**: `Get-NetTCPConnection -LocalPort 8000` — a real `Listen` entry with an `OwningProcess` PID; cross-check against `Get-Process -Id <pid>` to confirm it's a genuine process, not a phantom stale entry.

**Resolution**: Kill every `python`/`uvicorn` process (`Get-Process | Where-Object {$_.ProcessName -match "python|uvicorn"} | Stop-Process -Force`), confirm the port is free, then start exactly one fresh process.

**Related Documentation**: [10-operations/recovery.md](../../10-operations/recovery.md).

---

## Problem: Which environment is "production" is genuinely unclear

**Symptoms**: Unsure whether Render or the EC2/systemd path (or both) is serving real traffic before making a risky change.

**Possible Causes**: Two deployment mechanisms coexist in this repository — `render.yaml` (2 services) and `.github/workflows/deploy.yml` (the only workflow that fires automatically, on every push to `main`, targeting EC2). This documentation pass could not determine which is authoritative from the repository alone.

**Resolution**: Confirm with whoever manages production infrastructure before assuming either. Don't guess based on which file "looks newer" — both are present and neither is marked deprecated in the repository itself.

**Related Documentation**: [09-deployment/environments.md](../../09-deployment/environments.md).

---

## Problem: `DEPLOYMENT.md`'s steps don't match `render.yaml`

**Symptoms**: Following the root `DEPLOYMENT.md` runbook references services (`rbac-backend`, `ticketing-backend`, etc.) that don't exist in the current `render.yaml`.

**Possible Causes**: `DEPLOYMENT.md` describes an older, 4-service topology that predates the backend consolidation into `unified-backend`. It was never updated after that consolidation.

**Resolution**: Ignore `DEPLOYMENT.md`'s specific steps; use [09-deployment](../../09-deployment/README.md) in this documentation set, which reconciles against the actual current `render.yaml`.

**Related Documentation**: [16-known-limitations](../../16-known-limitations/README.md).

---

## Problem: Health check passes but the deploy didn't actually pick up the latest code

**Symptoms**: `deploy.yml`'s `curl 127.0.0.1:8001/health` succeeds, but the deployed behavior still reflects an older version.

**Possible Causes**: `/health` is a pure liveness check — it says nothing about whether the running process is genuinely the freshly-restarted one, or whether `git merge --ff-only` actually succeeded (a diverged EC2 checkout would fail that step, but the workflow's later steps and health check could still pass against the *old*, unchanged checkout, depending on exact script behavior not fully visible in `deploy.yml` alone).

**How to Diagnose**: Check the GitHub Actions job log for the `git merge --ff-only` step's actual output, not just the final health-check status.

**Resolution**: Treat a green health check as necessary, not sufficient, confirmation of a successful deploy — also verify the Actions log shows the merge step succeeded.

**Related Documentation**: [09-deployment/health-checks.md](../../09-deployment/health-checks.md).
