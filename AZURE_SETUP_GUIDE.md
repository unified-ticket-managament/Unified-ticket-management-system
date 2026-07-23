# Azure Setup Guide — Microsoft Graph Email Integration

Step-by-step runbook for provisioning the Azure/Microsoft 365 side of a future Microsoft Graph email integration for this project, and wiring the resulting credentials into the existing Render deployment. No source code was changed to produce this guide.

## Before you start: this is a setup guide for infrastructure, not a description of a finished integration

Per `EMAIL_INTEGRATION_ANALYSIS.md` / `EMAIL_INTEGRATION_CHECKLIST.md` / `GRAPH_AUTHENTICATION.md`, **no Graph client code exists in this repo yet** — no MSAL auth, no `GraphMailProviderClient`, and critically, no `validationToken`/`clientState` handling on `POST /api/mail/incoming` (its own docstring warns not to point a real subscription at it until that's added). Completing every step below gives you valid Azure credentials and a mailbox ready to use — it does **not**, by itself, make inbound/outbound Graph mail work end-to-end. Backend code implementing the pieces listed in `EMAIL_INTEGRATION_CHECKLIST.md`'s "Missing items" section still needs to be written afterward.

This guide is organized in the order you'd actually perform these steps, not the order they were listed in the request.

---

## 1. Azure App Registration

You need an Azure AD (Entra ID) app registration to authenticate this backend against Microsoft Graph using the **client credentials flow** (app-only, no signed-in user — appropriate for a backend service acting on a shared mailbox).

1. Sign in to the [Azure Portal](https://portal.azure.com) with an account that has permission to register applications in the target tenant (Application Administrator or Global Administrator role, or a tenant with user app-registration self-service enabled).
2. Navigate to **Microsoft Entra ID** → **App registrations** → **New registration**.
3. Fill in:
   - **Name**: something identifiable, e.g. `unified-backend-graph-mail` (matches this repo's own `unified-backend` naming).
   - **Supported account types**: "Accounts in this organizational directory only (Single tenant)" — this is an internal service integration, not a multi-tenant app.
   - **Redirect URI**: leave blank. Client-credentials flow is a server-to-server exchange; it does not use a redirect/callback URL the way an interactive user-login flow would.
4. Click **Register**.
5. You'll land on the app's **Overview** page — this is where you'll copy the Tenant ID and Client ID (§2, §3).

## 2. Tenant ID

On the app registration's **Overview** page, copy the **Directory (tenant) ID** field — a GUID, e.g. `72f988bf-86f1-41af-91ab-2d7cd011db47` (example format only, not a real value).

This identifies which Azure AD directory the app is registered in and is required for every token request (`https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token`).

This maps to the proposed `GRAPH_TENANT_ID` setting from `EMAIL_ENVIRONMENT_GUIDE.md` — not currently a real field in `unified-backend/app/core/config.py`; adding it is part of the not-yet-written Graph client code.

## 3. Client ID

On the same **Overview** page, copy the **Application (client) ID** field — a separate GUID from the tenant ID.

This identifies the app registration itself and is sent alongside the client secret when requesting a token. Maps to the proposed `GRAPH_CLIENT_ID` setting.

## 4. Client Secret

The app registration needs a secret (or certificate) to prove its identity when requesting tokens — this is the actual credential and must be handled like any other production secret in this project (same sensitivity tier as `JWT_SECRET_KEY`).

1. On the app registration, go to **Certificates & secrets** → **Client secrets** tab → **New client secret**.
2. Give it a description (e.g. `unified-backend-prod`) and choose an expiration (Azure's dropdown typically offers 3, 6, 12, 18, or 24 months, or a custom date — **avoid "never expires" if offered**, since a non-expiring secret is a larger standing risk than a rotation reminder).
3. Click **Add**. **The secret VALUE is shown only once, immediately after creation** — copy it now into a secure location (a password manager, or directly into the Render dashboard per §10) before navigating away. If you lose it, you must generate a new one; Azure cannot show it again.
4. Note the secret's **expiration date** somewhere durable (a calendar reminder, an internal wiki page) — an expired secret will cause every Graph API call to start failing with an authentication error, and nothing in this repo currently monitors for that (see `EMAIL_INTEGRATION_CHECKLIST.md`'s Deployment section).

Maps to the proposed `GRAPH_CLIENT_SECRET` setting — **must** be stored only as a Render environment variable (marked secret) or local `.env` (already git-ignored per `unified-backend/.gitignore`), never committed, never logged.

**Alternative — certificate credential**: Azure also supports uploading a public certificate instead of a secret ("Certificates" tab, same blade). Certificates are longer-lived and often preferred for production service-to-service auth, but require managing a private key file rather than a single string — outside this guide's scope, but worth considering if this integration graduates from a first pass to a long-term production credential.

## 5. Graph Permissions

The app needs explicit Microsoft Graph API permissions, granted as **Application** permissions (not "Delegated" — there is no signed-in user in this flow, matching your client-credentials auth choice above).

1. On the app registration, go to **API permissions** → **Add a permission** → **Microsoft Graph** → **Application permissions**.
2. Add:
   - **`Mail.Send`** — required for outgoing email (the future replacement for `MockMailProviderClient.send_email` in `services/mail_provider.py`).
   - **`Mail.Read`** (or `Mail.ReadWrite` if the future implementation needs to mark messages as read or move them after processing — decide this when the actual inbound-fetch code is written; `Mail.Read` is the minimum for receiving).
3. Remove the default `User.Read` **delegated** permission if present — it's irrelevant to an app-only flow and unnecessarily widens the registration's footprint.

**Scope this to one mailbox, not the whole tenant** — see §7 (Application Access Policy); Graph application permissions alone would otherwise let this app read/send mail for *every* mailbox in the organization, which is far more than this integration needs.

## 6. Admin Consent

Application permissions on Microsoft Graph always require **tenant administrator consent** — an individual developer cannot self-consent to these regardless of their own role.

1. Still on **API permissions**, you'll see each added permission listed with a status column showing "Not granted for `<tenant>`".
2. If you have Global Administrator or Privileged Role Administrator rights: click **Grant admin consent for `<tenant>`**, then confirm. The status column should update to a green checkmark for both `Mail.Send` and `Mail.Read`.
3. If you don't have that role: send the app's **Application (client) ID** to whoever administers your Microsoft 365 tenant and ask them to grant admin consent for it — they can do this from the same **API permissions** blade if they have access to the app registration, or via the **Enterprise applications** view.
4. **Do not proceed to subscription creation or a live send test until this shows granted** — every Graph API call will fail with an authorization error until consent is recorded.

## 7. Shared Mailbox

The mailbox this integration sends from and receives into should be a dedicated **shared mailbox**, not a real employee's personal inbox — this matches the existing pattern in this codebase, where `Client.inbox_email` is already a dedicated per-client shared address (see `email_envelope.py`'s "From is always the client's shared inbox, never an agent's personal address" rule).

1. In the **Microsoft 365 admin center** (admin.microsoft.com) → **Teams & groups** → **Shared mailboxes** → **Add a shared mailbox**.
2. Choose a name and address, e.g. `support@yourdomain.com` or matching whichever existing client inbox address this integration is meant to replace/augment.
3. Shared mailboxes don't require their own license for basic mail flow, but confirm your tenant's specific licensing requirements for Graph API access to a shared mailbox (this can vary by tenant configuration).

**Scope the app registration's access to only this mailbox** via an Exchange Online **Application Access Policy** — otherwise the `Mail.Send`/`Mail.Read` application permissions from §5 grant access to *every* mailbox in the tenant by default, which is unnecessarily broad:

```powershell
# Run in Exchange Online PowerShell, connected as an Exchange admin
New-ApplicationAccessPolicy `
  -AppId "<client-id-from-step-3>" `
  -PolicyScopeGroupId "support@yourdomain.com" `
  -AccessRight RestrictAccess `
  -Description "Restrict unified-backend Graph app to the shared support mailbox only"
```

Maps to the proposed `GRAPH_MAILBOX_ADDRESS` setting.

## 8. Webhook URL

This is the URL Microsoft Graph will call whenever a new email arrives (a "change notification"). It must be:

- **Publicly reachable over HTTPS** — Graph will not deliver notifications to `localhost` or a private network address. For local development/testing before this is deployed, use a tunneling tool (e.g. `ngrok http 8000`) to get a temporary public HTTPS URL.
- **Pointed at `unified-backend`'s existing `/api/mail/incoming` route** (`api/mail_integration.py`) — or a new, dedicated route if you decide the validation/`clientState` work belongs on a separate path instead of retrofitting this one; that's an implementation decision for whoever writes the missing code, not something this guide prescribes.
- **Confirmed stable before you create a subscription** (§9) — the deployed `unified-backend` Render service's URL follows the pattern `https://unified-backend-xxxx.onrender.com` (exact subdomain assigned by Render on first deploy; check the Render dashboard's service page for the real value, the same "confirm after first deploy" step this repo's own `render.yaml`/`DEPLOYMENT.md` already require for `CORS_ORIGINS` and the `NEXT_PUBLIC_*` frontend URLs). A URL change later means re-creating the subscription, not just updating a setting.

**Before pointing a live subscription here**: remember the validation gap from `EMAIL_RECEIVE_FLOW.md` — Graph's subscription-creation handshake calls this URL once with a `validationToken` query parameter that must be echoed back as plain text, synchronously, within a few seconds, or subscription creation itself will fail. That handling does not exist in `api/mail_integration.py` today and must be added first.

Maps to the proposed `GRAPH_WEBHOOK_CLIENT_STATE` setting for the anti-spoofing secret (distinct from the URL itself) — a value **you** generate (e.g. a random 32+ character string), not something Azure issues.

## 9. Subscription creation

Once the app has a validated webhook URL (§8) and admin-consented permissions (§6), create the Graph subscription that actually starts delivering notifications. This is a Graph API call your future backend code (or a one-time setup script) makes — it is not an Azure Portal button.

Example request (illustrative — this is a `curl`/HTTP call against Graph itself, using an access token obtained via the client-credentials flow with the credentials from §2–§4):

```http
POST https://graph.microsoft.com/v1.0/subscriptions
Authorization: Bearer <app-access-token>
Content-Type: application/json

{
  "changeType": "created",
  "notificationUrl": "https://unified-backend-xxxx.onrender.com/api/mail/incoming",
  "resource": "/users/support@yourdomain.com/mailFolders('Inbox')/messages",
  "expirationDateTime": "2026-07-24T10:00:00Z",
  "clientState": "<the-same-secret-value-from-step-8>"
}
```

Key points:
- **`expirationDateTime`**: Graph mail subscriptions expire after a maximum of roughly 3 days (4,230 minutes) from creation — there is no "subscribe once, forever" option. A **renewal job** must call `PATCH /subscriptions/{id}` with a new `expirationDateTime` before it lapses, or notifications silently stop. `EMAIL_INTEGRATION_CHECKLIST.md` recommends wiring this as another in-process APScheduler job, following the same pattern this repo already uses for `SLASweepService` (`app/core/sla_scheduler.py`) — one process, one scheduler, no second external cron.
- **`clientState`**: echoed back by Graph on every notification; your webhook handler must verify it matches before trusting the notification (this is the check `api/mail_integration.py`'s docstring says doesn't exist yet).
- **`resource`**: scoped to the specific shared mailbox's Inbox folder from §7 — not a tenant-wide subscription.
- The response includes a subscription `id` — store it (e.g. in a new DB table, or Graph-related config) so the renewal job knows what to renew.

## 10. Render environment variables

This project's existing convention (see `render.yaml` and `EMAIL_ENVIRONMENT_GUIDE.md`) is: secrets marked `sync: false` in `render.yaml` are **pasted directly into the Render dashboard**, never hardcoded in the file. The Graph-related variables don't exist in `render.yaml` yet — adding them there is a code/config change, which this guide deliberately does not perform (per "do not modify source code"). Instead, add them **only via the Render dashboard** for now, under the `unified-backend` service's **Environment** tab:

| Key | Value | Notes |
|---|---|---|
| `GRAPH_TENANT_ID` | From §2 | Not secret in the strictest sense, but follow this repo's existing convention of treating even non-secret IDs as dashboard-set (same as `SUPABASE_URL` today) |
| `GRAPH_CLIENT_ID` | From §3 | Same as above |
| `GRAPH_CLIENT_SECRET` | From §4 | **Mark as a secret value in the Render dashboard.** Equivalent sensitivity to `JWT_SECRET_KEY`/`SLA_SWEEP_SHARED_SECRET` |
| `GRAPH_MAILBOX_ADDRESS` | From §7, e.g. `support@yourdomain.com` | Not secret |
| `GRAPH_WEBHOOK_CLIENT_STATE` | The secret string you generated in §8 | **Mark as a secret value.** This is the only thing preventing a forged webhook call from being accepted once the validation code exists |

Steps:
1. Render dashboard → your `unified-backend` service → **Environment**.
2. **Add Environment Variable** for each row above.
3. Click **Save Changes** — Render will trigger a redeploy of `unified-backend` automatically (same behavior as any other env var change on this service).
4. Once the corresponding `Settings` fields and Graph client code exist (see `EMAIL_INTEGRATION_CHECKLIST.md`), these values will be read the same way every other secret in `config.py` already is — no default, fail fast at boot, matching this repo's existing convention for `database_url`/`jwt_secret_key`/`sla_sweep_shared_secret`.

**When the corresponding code is actually written**, these same four (or five, if `GRAPH_API_BASE_URL` is added) keys should also be added to `render.yaml` itself as `sync: false` entries with explanatory comments — matching every other secret already declared there — so a fresh Blueprint deploy doesn't silently omit them. That's a source-code change and is intentionally left out of this guide.

---

## Summary checklist

- [ ] App registration created (§1)
- [ ] Tenant ID and Client ID recorded (§2, §3)
- [ ] Client secret generated and stored securely, expiration date tracked (§4)
- [ ] `Mail.Send` + `Mail.Read` Application permissions added (§5)
- [ ] Admin consent granted (§6)
- [ ] Shared mailbox created, Application Access Policy scoped to it (§7)
- [ ] Webhook URL confirmed stable and publicly reachable over HTTPS (§8)
- [ ] **Backend code for `validationToken`/`clientState` handling written and deployed** (not part of this guide — see `EMAIL_INTEGRATION_CHECKLIST.md`) before attempting §9
- [ ] Subscription created against Graph, renewal job planned (§9)
- [ ] All five Graph environment variables added to the Render dashboard (§10)
