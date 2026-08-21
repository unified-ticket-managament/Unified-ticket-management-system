# Alerts

## What exists today

No dedicated alerting system (PagerDuty, Opsgenie, a Slack webhook on error, etc.) was found in the repository. The closest things to "alerts" this system has are:

- **In-app/email notifications to end users** — `SLA_BREACHED` (email-eligible), `ESCALATION_CREATED` (email-eligible), and the rest of the SLA/escalation ladder (in-app only) — these alert *business users* to a ticket-level problem, not *operators* to a system-level problem. Don't conflate the two.
- **The EC2 deploy workflow's own health-check gate** — `deploy.yml` fails the GitHub Actions job (visible in the Actions tab, and email-notifiable via GitHub's own notification settings if configured) if `/health` doesn't respond post-restart. This is the closest thing to an operational alert that exists, and it only covers "did this specific deploy succeed."
- **Render's platform-level alerting** — Render itself may offer deploy-failure/service-down notifications through its own dashboard (a platform feature, not something this repository configures) — **not confirmed** whether this is set up for this project.

## What was NOT found

- No alert for the SLA sweep silently failing/stopping.
- No alert for the Microsoft Graph webhook subscription lapsing (it needs periodic renewal — `graph_subscription_scheduler.py` — a failure here would silently degrade to the polling fallback, or stop working entirely if polling isn't also configured).
- No alert for connection-pool exhaustion.
- No alert for outbound email delivery failures (these are caught and logged per-recipient, never surfaced beyond a log line).

## Recommendation

Given the in-process, single-instance nature of this system's background jobs (SLA sweep, Graph subscription renewal), a genuinely valuable, low-effort addition would be a periodic external check (even a simple uptime monitor hitting `/health`, or a scheduled query confirming recent `sla_breach_notifications` activity matches expected sweep cadence) — not present today. See [17-roadmap](../17-roadmap/README.md) for whether this is tracked anywhere as planned work (it is not, as of this pass).
