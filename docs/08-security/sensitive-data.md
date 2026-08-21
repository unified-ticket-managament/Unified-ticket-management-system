# Sensitive Data

## What's stored

- **Credentials**: `users.password_hash` (bcrypt) — never the plaintext password.
- **PII**: `users.email`, `.alternate_email`, `.phone_number`, `.date_of_birth`, `.office_location` — real profile data for every internal employee (see [08-security/phi-pii-handling.md](phi-pii-handling.md)).
- **Client communication content**: full email bodies (HTML and plain-text), attachments, in `interactions.payload` and the storage backend.
- **Audit trails**: `old_values`/`new_values` JSONB on both audit tables — capable of holding a diff of any field, including potentially sensitive ones, for whatever action triggered the log.

## What's NOT stored (confirmed)

- No API keys/secrets are stored in application tables — all live in environment variables only (see [secrets-management.md](secrets-management.md)).
- No plaintext passwords anywhere.

## Logging discipline

- `logging.basicConfig` is configured once, in `main.py`, at `LOG_LEVEL` (default INFO).
- **Not exhaustively audited in this pass**: whether any log statement anywhere in the ~30 ticketing service files or ~12 rbac service files ever logs a full request body, a token, or a password. Given the scale of the codebase, treat this as an open item — grep for `logger.debug`/`logger.info` calls near auth/payload-heavy code paths before assuming nothing sensitive is logged.
- The audit-log system's own `old_values`/`new_values` fields are a **structural** place sensitive data could end up recorded (e.g. a profile-field diff capturing a phone number change) — this is by design (it's what an audit trail is for) but means audit-log read access (`audit:view`/`ticket:view_global_audit_log`) is itself a sensitive-data access control point.

## Email content

Inbound/outbound email bodies pass through `beautifulsoup4` for HTML→plain-text conversion, and are stored in `interactions.payload` (JSONB) — this field can contain anything a client or agent wrote, with no field-level classification or redaction applied anywhere in the pipeline that this pass could confirm.

## Data in transit

- Browser ↔ backend: HTTPS (enforced at the infrastructure/proxy layer — Render or the EC2 host's reverse proxy/load balancer; **not confirmed** whether the FastAPI app itself enforces TLS termination or relies entirely on the hosting layer).
- Backend ↔ Neon: `DATABASE_URL`'s `sslmode`/`ssl` parameter (normalized by `Settings.normalize_database_url`) — confirms SSL is at least configured for the DB connection.
- Backend ↔ Microsoft Graph: HTTPS (Graph API requirement).

## Recommendation

Given this system carries real employee PII and (per its healthcare-industry client base — see [phi-pii-handling.md](phi-pii-handling.md)) likely handles healthcare-adjacent client communications, a dedicated data-classification pass (which fields are PII/PHI, who can read them, how long they're retained) would be valuable future work — **not found to exist** in this repository today.
