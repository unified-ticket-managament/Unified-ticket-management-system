# Clients, Categories, Mail Folders & Rules API

## Clients — `app/ticketing/api/client.py` (prefix `/clients`)

| Method | Path | Purpose | Auth |
|---|---|---|---|
| POST | `/clients` | Onboard a new client company | `get_current_agent` |
| GET | `/clients` | List every onboarded client | `get_current_user` |
| GET | `/clients/{id}/details` | Aggregated client detail view | `get_current_user` + `ensure_can_view_client_details` (`client:view`) |
| GET | `/clients/{id}/contacts` | Distinct contact emails for a client (optional `configured_only`) | `get_current_user` (deliberately ungated) |

## Categories (ticketing domain) — `app/ticketing/api/category.py` (prefix `/categories`)

| Method | Path | Purpose | Auth |
|---|---|---|---|
| GET | `/categories` | List every work-specialization category | `get_current_user` |

This is a **separate endpoint** from the RBAC-domain `/api/v1/categories` CRUD group (see [users-roles-permissions.md](users-roles-permissions.md)) — this one is read-only and unprefixed, used by the ticket workspace for category pickers/filters. **As of 2026-08-21, `category_name` is a dynamically-created plain string, not a fixed enum** — see [06-database/database-overview.md](../06-database/database-overview.md); this read-only endpoint's shape is unchanged, it simply now reflects whatever categories currently exist rather than a fixed set of 8.

## Mail Folders — `app/ticketing/api/mail_folder.py` (prefix `/folders`)

| Method | Path | Purpose | Auth |
|---|---|---|---|
| GET | `/folders` | List every custom mail folder (global, not per-user) | `get_current_agent` |
| POST | `/folders` | Create a mail folder | `get_current_agent` |
| DELETE | `/folders/{id}` | Delete a mail folder | `get_current_agent` |

## Mail/OTP Rules — `app/ticketing/api/rule.py` (prefix `/rules`)

| Method | Path | Purpose | Auth |
|---|---|---|---|
| GET | `/rules` | List every Mail Rule and OTP Rule | `get_current_agent` + `rule:manage` (enforced in service) |
| GET | `/rules/{id}` | Get rule details | `get_current_agent` |
| POST | `/rules` | Create rule | `get_current_agent` |
| PUT | `/rules/{id}` | Update rule | `get_current_agent` |
| PATCH | `/rules/{id}/enabled` | Toggle a rule on/off | `get_current_agent` |
| POST | `/rules/{id}/reorder` | Move a rule within its category's priority order | `get_current_agent` |
| DELETE | `/rules/{id}` | Delete rule | `get_current_agent` |

**Business rule**: a rule's `client` condition, if present, is an **exact-match filter** — it does not implicitly also cover "any client without a client condition." A rule scoped to the wrong client (or misconfigured during editing) silently never fires for the client its name implies. See [14-troubleshooting/email](../14-troubleshooting/email/) for a real incident this caused.

**OTP Rule category**: `RuleEngineService.evaluate_and_execute_for_email` checks `rule.category == RuleCategory.OTP_RULE` — generic to whatever condition fields the rule was configured with, never hardcoded to a literal phrase. **As of 2026-08-21, an OTP Rule match no longer has any effect on First Response SLA completion** — that decision is now made by a separate, independent heuristic classifier (`otp_classifier.py`) evaluated *before* the rule engine runs at all. An OTP Rule still controls folder filing and `forward_to` employee notifications exactly as before. See [04-functional-modules/ai-nlp.md](../04-functional-modules/ai-nlp.md) and [03-business-workflows/communication/email-processing.md](../03-business-workflows/communication/email-processing.md).
