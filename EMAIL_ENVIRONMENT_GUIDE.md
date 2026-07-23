# Email Integration — Environment Variable Guide

Verification of `unified-backend`'s environment configuration against what email integration (existing SMTP + future Microsoft Graph) actually needs. Sources checked: `unified-backend/app/core/config.py` (the `Settings` model, full file read), `render.yaml` (repo root, the only Render Blueprint), and `.env.example` (searched — see finding below). No files were modified.

---

## 0. A finding before the checklist: there is no backend `.env.example`

`unified-backend/` has a real, git-ignored `.env` (confirmed via `git check-ignore` — it's untracked, as it should be for a file holding `DATABASE_URL`/`JWT_SECRET_KEY`/etc., and its contents were **not** read for this report) but **no `.env.example` file exists anywhere under `unified-backend/`**. Only the two frontends have one (`unified-frontend/.env.example`, `ticketing-service/frontend/.env.example`).

This matters directly for email/Graph work: there is currently no checked-in template listing which env vars the backend expects, SMTP or otherwise — a new developer (or a future Graph implementation) has nothing to copy from except `config.py` itself. This is listed as a missing item below.

---

## 1. Missing variables

### 1a. Currently missing and already needed (SMTP, real feature, not future work)

None. Every SMTP field declared in `config.py` (`smtp_host`, `smtp_port`, `smtp_username`, `smtp_password`, `smtp_from_email`, `smtp_use_tls`) is optional with a working code default/fallback (`LoggingEmailSender` when `smtp_host` is unset), so nothing is "missing" in the sense of breaking the app. What's missing is **operational**, not code-level — see §1c.

### 1b. Missing for Microsoft Graph (none of these exist anywhere — not in `config.py`, not in any `.env.example`, not in `render.yaml`)

Per `EMAIL_INTEGRATION_ANALYSIS.md`'s finding that no Graph code exists yet, none of its required configuration exists either. If/when `GraphMailProviderClient` (see `EMAIL_INTEGRATION_CHECKLIST.md`) is built, it will need new `Settings` fields — proposed names below follow this repo's existing snake_case-to-UPPER_SNAKE_CASE convention:

| Proposed `Settings` field | Proposed env var | Purpose |
|---|---|---|
| `graph_tenant_id` | `GRAPH_TENANT_ID` | Azure AD tenant ID |
| `graph_client_id` | `GRAPH_CLIENT_ID` | App registration's client ID |
| `graph_client_secret` | `GRAPH_CLIENT_SECRET` | App registration's client secret (or swap for a certificate credential — see below) |
| `graph_mailbox_address` | `GRAPH_MAILBOX_ADDRESS` | The shared mailbox UPN/address to send from and receive into |
| `graph_webhook_client_state` | `GRAPH_WEBHOOK_CLIENT_STATE` | App-generated secret Graph echoes back on every notification, for anti-spoofing verification |
| `graph_api_base_url` | `GRAPH_API_BASE_URL` | Optional; only needed if pinning a non-default Graph API version (defaults to `v1.0` if omitted) |

None of these should have a hardcoded default in code — following this repo's own established pattern for the analogous secret-bearing fields (`database_url`, `jwt_secret_key`, `sla_sweep_shared_secret` all have **no** default and fail fast at boot per `config.py`'s own comments), `graph_client_id`/`graph_client_secret`/`graph_webhook_client_state` should be required-with-no-default once Graph is actually wired in, not `str | None = None` — otherwise the app would boot "successfully" into a half-configured Graph integration that fails confusingly on first use instead of at startup.

### 1c. Missing operationally (exists in code, absent from `render.yaml`)

`render.yaml`'s `unified-backend` service does **not** declare any of the six `smtp_*` keys, nor `APP_FRONTEND_URL`, even though all seven are real `Settings` fields already consumed by working code (`app/core/email_sender.py`, `sla_breach_notifier.py`). Since `render.yaml` env vars marked `sync: false` are the ones documented as "paste into the Render dashboard," and these aren't listed at all, there is no Blueprint-driven reminder to ever set them in production. Practical implication: **unless someone has manually added `SMTP_HOST` etc. directly in the Render dashboard outside the Blueprint, the deployed backend is running on `LoggingEmailSender` (log-only, no real SLA-breach notification email ever leaves production)**. This report can't confirm the live dashboard state (out of scope — no deploy access), only that the Blueprint itself doesn't provision it.

## 2. Incorrect names

**None found.** Every env var key in `render.yaml`'s `unified-backend` block that corresponds to a `Settings` field matches that field's name exactly under the expected `snake_case` → `UPPER_SNAKE_CASE` convention (`pydantic-settings` with `case_sensitive=False`), e.g. `SMTP_HOST` would correctly bind to `smtp_host` if it were present. Checked every one of the 19 keys currently in the Blueprint's `unified-backend` section against `config.py` field-by-field; all match or are intentionally not `Settings` fields (see next point).

One near-miss worth flagging so it's never mistaken for a bug: `ALEMBIC_DATABASE_URL` appears in `render.yaml` but has **no** corresponding field in `Settings` at all. This is correct as-is, not an error — per `render.yaml`'s own comment, `alembic_ticketing/env.py` reads that variable directly via `os.environ`, bypassing the pydantic `Settings` model entirely, while `alembic_rbac`'s chain instead derives its sync URL from `DATABASE_URL`. Not an email-integration concern, but noted since it's the one env var in the file that doesn't map onto `Settings` and could otherwise look like a typo.

## 3. Unused variables

**None found among the existing SMTP/email fields.** All six `smtp_*` fields and `app_frontend_url` are read by real code:

- `smtp_host` — `email_sender.py:116` (gate for `LoggingEmailSender` vs. `SMTPEmailSender`)
- `smtp_port`, `smtp_username`, `smtp_password`, `smtp_from_email`, `smtp_use_tls` — all passed into `SMTPEmailSender` construction, `email_sender.py:120-125`
- `app_frontend_url` — `sla_breach_notifier.py:118`, used to build a clickable absolute link in outbound notification emails

No dead/unreferenced email-related config field exists in `config.py` today.

## 4. Variables that should remain secret

Applies to both what exists today and what Graph will need. "Secret" here means: never committed, never logged, stored only in the platform's secret store (Render env var marked sensitive, or local `.env` which is already git-ignored).

### Already secret today (confirm handling, no changes needed)
- `SMTP_USERNAME`, `SMTP_PASSWORD` — mailbox/relay credentials
- `DATABASE_URL`, `ALEMBIC_DATABASE_URL` — DB credentials embedded in the connection string
- `JWT_SECRET_KEY` — token-signing key
- `SLA_SWEEP_SHARED_SECRET` — internal auth secret
- `SUPABASE_SERVICE_ROLE_KEY` — storage service-role key

### Not secret (safe as plain config)
- `SMTP_HOST`, `SMTP_PORT`, `SMTP_FROM_EMAIL`, `SMTP_USE_TLS` — configuration, not credentials
- `APP_FRONTEND_URL` — a public URL

### Will need secret handling once Graph is built
- `GRAPH_CLIENT_SECRET` — highest sensitivity of the proposed Graph vars; equivalent in risk to `JWT_SECRET_KEY`/`SLA_SWEEP_SHARED_SECRET` and should get the same "no default, fail fast at boot" treatment
- `GRAPH_WEBHOOK_CLIENT_STATE` — must stay secret; it's the only thing preventing a forged webhook notification from being accepted (this is exactly the check `api/mail_integration.py`'s own docstring flags as "not implemented yet")
- `GRAPH_TENANT_ID`, `GRAPH_CLIENT_ID` — not secret in the strict sense (Microsoft documents these as discoverable/semi-public identifiers, e.g. visible in browser network traffic during any OAuth flow), but this repo's own convention (`SUPABASE_URL` is `sync: false` alongside its actual secret key) treats even non-secret IDs as `sync: false`/dashboard-pasted rather than hardcoded in `render.yaml` — worth following for consistency even though the confidentiality requirement is lower
- `GRAPH_MAILBOX_ADDRESS` — not sensitive, safe as plain config (comparable to `SMTP_FROM_EMAIL`)

If a certificate credential is chosen instead of `GRAPH_CLIENT_SECRET` (mentioned as an option in `EMAIL_INTEGRATION_CHECKLIST.md`'s Azure dependencies), the private key material carries the same "never commit, never log" requirement — likely stored as a file-based secret rather than a single env var, which would need a different mechanism than the flat `key`/`sync: false` pattern `render.yaml` uses for everything else today.

---

## Summary table — current state

| Variable | Declared in `config.py`? | Declared in `render.yaml`? | Has an `.env.example`? | Used by real code? |
|---|---|---|---|---|
| `SMTP_HOST` | Yes (optional) | No | No (file doesn't exist) | Yes |
| `SMTP_PORT` | Yes (default 587) | No | No | Yes |
| `SMTP_USERNAME` | Yes (optional) | No | No | Yes |
| `SMTP_PASSWORD` | Yes (optional) | No | No | Yes |
| `SMTP_FROM_EMAIL` | Yes (optional) | No | No | Yes |
| `SMTP_USE_TLS` | Yes (default true) | No | No | Yes |
| `APP_FRONTEND_URL` | Yes (optional) | No | No | Yes |
| `GRAPH_TENANT_ID` | No | No | No | No (feature not built) |
| `GRAPH_CLIENT_ID` | No | No | No | No |
| `GRAPH_CLIENT_SECRET` | No | No | No | No |
| `GRAPH_MAILBOX_ADDRESS` | No | No | No | No |
| `GRAPH_WEBHOOK_CLIENT_STATE` | No | No | No | No |

**Net assessment**: no incorrect or unused variables exist in the current email-related configuration — the gaps are entirely omissions (no backend `.env.example` at all, SMTP vars absent from the Render Blueprint, and the complete absence of any Graph-related configuration, consistent with Graph integration not being implemented yet per `EMAIL_INTEGRATION_ANALYSIS.md`).
