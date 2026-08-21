# Security Enhancements

## Already done (confirmed, not proposals)

The 2026-07-14/15 RBAC permission compliance audit fixed several real, confirmed gaps: the missing `await` on `AttachmentService.upload_attachment`'s authorization check; an unconditional Team-Lead close/reopen bypass; missing Account-Manager-ownership checks on several mutating actions; the first real permission checks on many RBAC-domain Users/Roles/Permissions/Audit-Log routes. See [15-architecture-decisions](../15-architecture-decisions/README.md).

## Genuine open opportunities

| Opportunity | Why it matters | Related |
|---|---|---|
| Add real permission checks to `permissions.py`'s create/update/delete routes | Currently authentication-only, no explicit permission check. (`categories.py`'s equivalent gap was closed 2026-08-21 with a real `category:create` check — a confirmed precedent for doing the same here.) | [08-security/authorization-rbac.md](../08-security/authorization-rbac.md) |
| Replace `/audit-logs`'s hardcoded `role.name == "Super Admin"` checks with a real permission | A future role rename would silently change who can manage this audit trail | [08-security/authorization-rbac.md](../08-security/authorization-rbac.md) |
| Confirm network-level protection (IP allowlist, shared secret) in front of the two unauthenticated inbound-mail webhook endpoints | Currently relying solely on Graph's `clientState` match; not confirmed whether anything else protects these in production | [08-security/authentication.md](../08-security/authentication.md) |
| Fix `AuthService.change_password`'s latent transient-object bug | Same shape as an already-fixed bug in `update_profile` | [14-troubleshooting/authentication/README.md](../14-troubleshooting/authentication/README.md) |
| A formal PHI/PII classification pass | No field-level data classification exists despite likely healthcare-adjacent client data | [08-security/phi-pii-handling.md](../08-security/phi-pii-handling.md) |
| Document and test an actual rollback procedure | No tested rollback runbook exists for either deployment path | [09-deployment/rollback.md](../09-deployment/rollback.md) |
| Real monitoring/alerting for scheduler health | A silently-stopped SLA sweep or lapsed Graph webhook subscription currently has no automated alert | [10-operations/alerts.md](../10-operations/alerts.md) |

## Deliberately not planned (a documented, considered decision, not a gap)

Additive-only permission overrides (no mechanism to grant a role X but revoke X for one person) — noted as a real architectural limitation during the compliance audit, left as-is, "flagged for whoever next revises the permission matrix doc" rather than scheduled.
