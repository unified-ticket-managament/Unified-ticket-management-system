# Postman Testing Guide — Email Endpoints

Complete Postman-ready documentation for every email-related endpoint in `unified-backend`, verified directly against source (`api/email.py`, `api/mail_integration.py`, `dependencies/auth.py`, `schemas/email.py`, `schemas/mail_integration.py`). No code was changed to produce this document.

**Base URL**: local dev is `http://localhost:8000` (see root `CLAUDE.md`'s "Local development" section). All routes below are mounted **unprefixed** — there is no `/api/v1` on any of them (that prefix is RBAC-only). Recommended Postman environment variable: `{{base_url}}`.

Endpoints covered:
1. `POST /emails/incoming` — real inbound transport (N8N-fed)
2. `POST /emails/dummy` — inbound simulator (Site Lead only)
3. `POST /api/mail/outgoing` — outgoing send (mocked provider)
4. `POST /api/mail/incoming` — Graph-shaped inbound sibling (demo only)

Plus a prerequisite section on obtaining a JWT, since two of the four require one.

---

## 0. Prerequisite — obtaining a JWT

`POST /emails/dummy` and `POST /api/mail/outgoing` both require an access token (`Depends(get_current_agent)`, `unified-backend/app/dependencies/auth.py`). RBAC is the sole token issuer (`unified-backend/app/rbac/api/v1/auth.py`).

### Request
- **Method**: `POST`
- **URL**: `{{base_url}}/api/v1/auth/login`
- **Headers**: `Content-Type: application/json`
- **Body** (raw JSON):
```json
{
  "email": "agent@painmedpa.com",
  "password": "your-password"
}
```

### Response — `200 OK`
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "refresh_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer"
}
```

Save `access_token` to a Postman environment variable, e.g. `{{access_token}}`. Use it as `Authorization: Bearer {{access_token}}` on every request below that requires auth.

**Role requirement note**: `POST /emails/dummy` additionally requires the logged-in user's role to be exactly `Site Lead` (`DUMMY_MAIL_ROLE_NAMES = {"Site Lead"}`, `services/access_control.py`); `POST /api/mail/outgoing` requires any role in `AGENT_ROLE_NAMES` (everyone except RBAC's client-facing "Viewer" role). Log in as the appropriate role for each request or you'll get a `403` (see each section's error table).

### Token refresh (optional, if your access token expires mid-testing)
- **Method**: `POST`
- **URL**: `{{base_url}}/api/v1/auth/refresh`
- **Body**: `{"refresh_token": "{{refresh_token}}"}`
- **Response**: same `TokenResponse` shape as login.

---

## 1. `POST /emails/incoming` — real inbound transport

The production inbound path, fed by an external N8N workflow. **Deliberately unauthenticated** — no Bearer token needed or checked.

### Request
| | |
|---|---|
| **Method** | `POST` |
| **URL** | `{{base_url}}/emails/incoming` |
| **Auth** | None |
| **Content-Type** | `multipart/form-data` (Postman: Body → form-data) |

### Headers
| Header | Value | Required |
|---|---|---|
| `Content-Type` | `multipart/form-data` (Postman sets this automatically when you use form-data body — do not set it manually, or the boundary will be wrong) | Yes (auto) |

### Request body (form-data fields)
| Key | Type | Required | Example |
|---|---|---|---|
| `to_email` | Text | Yes | `intake@painmedclient.com` |
| `from_email` | Text | Yes | `patient@example.com` |
| `from_name` | Text | No | `Jane Alvarez` |
| `subject` | Text | Yes | `Question about my last visit` |
| `body` | Text | Yes | `Hi, I had a question about...` |
| `html_body` | Text | No | `<p>Hi, I had a question...</p>` |
| `message_id` | Text | Yes | `<abc123@example.com>` — must be unique per test run, see duplicate-detection error below |
| `received_at` | Text | No | `2026-07-21T10:00:00Z` (ISO 8601) |
| `in_reply_to` | Text | No | `<previous-message-id@example.com>` |
| `references` | Text | No | Space-separated Message-IDs, e.g. `<id1@x.com> <id2@x.com>` |
| `conversation_id` | Text | No | `AAQkAGI2...` (Graph-style thread id, accepted but not required) |
| `files` | File | No | Attach one or more files (multi-select in Postman's form-data file field) |

### Example success response — `201 Created`
```json
{
  "message": "Email received successfully.",
  "interaction_id": "3f9a1c2e-1234-4a56-8abc-9e0f1a2b3c4d",
  "client_id": "1a2b3c4d-5e6f-7890-abcd-ef1234567890",
  "client_name": "Example Pain Clinic",
  "ticket_id": null,
  "threaded_under": null,
  "status": "PENDING",
  "attachments": []
}
```
(`ticket_id`/`threaded_under` are populated when the email matches an existing thread — see `EMAIL_RECEIVE_FLOW.md` for the matching logic.)

### Expected errors
| Status | Condition | Response body |
|---|---|---|
| `409 Conflict` | `message_id` already exists in the database (duplicate delivery/retry) | `{"detail": "Email already processed."}` |
| `404 Not Found` | `to_email` doesn't match any active client's shared inbox address | `{"detail": "Unknown inbox address."}` |
| `400 Bad Request` | Any other `ValueError` raised inside `EmailService.receive_email` | `{"detail": "<message>"}` |
| `422 Unprocessable Entity` | Missing a required form field, or an invalid email format on `to_email`/`from_email` | Standard FastAPI/Pydantic validation error body |

---

## 2. `POST /emails/dummy` — inbound simulator (Site Lead only)

Runs through the exact same `EmailService.receive_email` as `/emails/incoming` — use this to simulate inbound mail from Postman without needing a real N8N delivery.

### Request
| | |
|---|---|
| **Method** | `POST` |
| **URL** | `{{base_url}}/emails/dummy` |
| **Auth** | Bearer token, **Site Lead role required** |
| **Content-Type** | `multipart/form-data` |

### Headers
| Header | Value | Required |
|---|---|---|
| `Authorization` | `Bearer {{access_token}}` | Yes |
| `Content-Type` | `multipart/form-data` (auto-set by Postman) | Yes (auto) |

### Request body
Identical form-data fields to `/emails/incoming` (see table above) — same schema, same optional/required rules.

### Example success response — `201 Created`
Identical shape to `/emails/incoming`'s response (same `EmailResponse` model).

### Expected errors
| Status | Condition | Response body |
|---|---|---|
| `401 Unauthorized` | Missing/invalid/expired Bearer token | `{"detail": "Invalid or expired token."}` (or `"Invalid access token."` / `"Invalid token payload."` depending on which check fails) |
| `403 Forbidden` | Valid token, but role is not `Site Lead` | `{"detail": "Only Site Lead can create dummy mail."}` |
| `403 Forbidden` | User account deactivated | `{"detail": "User account is inactive."}` |
| `409 Conflict` | Duplicate `message_id` | `{"detail": "Email already processed."}` |
| `404 Not Found` | Unknown `to_email` | `{"detail": "Unknown inbox address."}` |
| `400 Bad Request` | Any other `ValueError` | `{"detail": "<message>"}` |
| `422 Unprocessable Entity` | Missing/invalid required field | Standard validation error body |

---

## 3. `POST /api/mail/outgoing` — outgoing send (mocked provider)

Sends via `MailProviderClient` — currently always `MockMailProviderClient` (no real delivery; see `EMAIL_INTEGRATION_ANALYSIS.md`). Requires an authenticated agent.

### Request
| | |
|---|---|
| **Method** | `POST` |
| **URL** | `{{base_url}}/api/mail/outgoing` |
| **Auth** | Bearer token, any role in `AGENT_ROLE_NAMES` (everyone except RBAC's "Viewer") |
| **Content-Type** | `application/json` |

### Headers
| Header | Value | Required |
|---|---|---|
| `Authorization` | `Bearer {{access_token}}` | Yes |
| `Content-Type` | `application/json` | Yes |

### Request body — Option A: send from a client's shared inbox
```json
{
  "client_id": "1a2b3c4d-5e6f-7890-abcd-ef1234567890",
  "to_email": "patient@example.com",
  "subject": "Following up on your recent visit",
  "body": "Hi, following up on your appointment last week..."
}
```

### Request body — Option B: explicit From address (no client)
```json
{
  "from_email": "no-reply@painmedpa.com",
  "from_name": "PainMed Billing",
  "to_email": "vendor@example.com",
  "cc": ["manager@painmedpa.com"],
  "bcc": [],
  "subject": "Vendor inquiry",
  "body": "Hello, we have a question about..."
}
```
`client_id` and `from_email` are mutually exclusive — supply exactly one, never both empty. There is **no attachment field** on this request model (a known gap — see `EMAIL_INTEGRATION_CHECKLIST.md`).

### Example success response — `201 Created`
```json
{
  "message": "Email dispatched successfully (mocked — Microsoft Graph integration pending).",
  "provider_message_id": "mock-3f9a1c2e123449a6ab...",
  "status": "SENT",
  "dispatched_at": "2026-07-21T14:32:10.123456+00:00",
  "envelope": {
    "from_email": "clientinbox@painmedclient.com",
    "from_name": null,
    "to_email": "patient@example.com",
    "cc": ["accountmanager@painmedpa.com"],
    "bcc": [],
    "subject": "Following up on your recent visit",
    "message_id": "<a1b2c3d4e5f6@painmedclient.com>",
    "in_reply_to": null,
    "references": [],
    "body": "Hi, following up on your appointment last week..."
  }
}
```
Note the response message itself confirms this is mocked — expect the identical string every time; this is not a placeholder in this documentation, it's the real literal API response.

### Expected errors
| Status | Condition | Response body |
|---|---|---|
| `401 Unauthorized` | Missing/invalid/expired Bearer token | `{"detail": "Invalid or expired token."}` |
| `403 Forbidden` | Role not in `AGENT_ROLE_NAMES` | `{"detail": "This account cannot act on tickets."}` |
| `404 Not Found` | `client_id` supplied but doesn't exist | `{"detail": "Client not found."}` |
| `422 Unprocessable Entity` | Both `client_id` and `from_email` omitted | Pydantic validator error: `"Either client_id or from_email must be provided."` |
| `422 Unprocessable Entity` | `subject`/`body` empty, or exceed max length (500/20000 chars respectively), or invalid email format on any address field | Standard FastAPI/Pydantic validation error body |

---

## 4. `POST /api/mail/incoming` — Graph-shaped inbound sibling (demo only)

Accepts a JSON body shaped like a Microsoft Graph `message` resource, maps it via `map_external_email_to_interaction()`, then reuses the same `EmailService.receive_email` as the other inbound routes. **Not a real Graph webhook receiver** — no `validationToken`/`clientState` handling exists (see `EMAIL_RECEIVE_FLOW.md`). Deliberately unauthenticated, same rationale as `/emails/incoming`.

### Request
| | |
|---|---|
| **Method** | `POST` |
| **URL** | `{{base_url}}/api/mail/incoming` |
| **Auth** | None |
| **Content-Type** | `application/json` |

### Headers
| Header | Value | Required |
|---|---|---|
| `Content-Type` | `application/json` | Yes |

### Request body
```json
{
  "internetMessageId": "<xyz789@outlook.com>",
  "subject": "Question about my last visit",
  "from": {
    "emailAddress": {
      "name": "Jane Alvarez",
      "address": "patient@example.com"
    }
  },
  "toRecipients": [
    {
      "emailAddress": {
        "name": "Intake",
        "address": "intake@painmedclient.com"
      }
    }
  ],
  "ccRecipients": [],
  "body": {
    "contentType": "text",
    "content": "Hi, I had a question about..."
  },
  "conversationId": "AAQkAGI2AAA=",
  "receivedDateTime": "2026-07-21T10:00:00Z",
  "internetMessageHeaders": [
    { "name": "In-Reply-To", "value": "<previous-id@example.com>" },
    { "name": "References", "value": "<id1@example.com> <id2@example.com>" }
  ]
}
```
Notes:
- `from` is the wire field name (Python-side alias for `from_` — Pydantic's `populate_by_name=True` means either works, but `from` is what a real Graph payload would send).
- `toRecipients[0]` is treated as the shared-inbox address that resolves the client — matches the same rule `/emails/incoming`'s `to_email` follows.
- **No attachment support** — there's no field for attachments on this schema, and `receive_incoming_email` never passes files to `receive_email` even if there were (see `EMAIL_RECEIVE_FLOW.md` §5). Don't expect attachments to appear on interactions created via this route.

### Example success response — `201 Created`
Identical `EmailResponse` shape to the other inbound routes:
```json
{
  "message": "Email received successfully.",
  "interaction_id": "3f9a1c2e-1234-4a56-8abc-9e0f1a2b3c4d",
  "client_id": "1a2b3c4d-5e6f-7890-abcd-ef1234567890",
  "client_name": "Example Pain Clinic",
  "ticket_id": null,
  "threaded_under": null,
  "status": "PENDING",
  "attachments": []
}
```

### Expected errors
| Status | Condition | Response body |
|---|---|---|
| `409 Conflict` | `internetMessageId` already exists (maps to the same `message_id` dedupe check) | `{"detail": "Email already processed."}` |
| `404 Not Found` | `toRecipients[0].emailAddress.address` doesn't match any active client | `{"detail": "Unknown inbox address."}` |
| `400 Bad Request` | Any other `ValueError` | `{"detail": "<message>"}` |
| `422 Unprocessable Entity` | Missing `internetMessageId`, missing/empty `toRecipients`, invalid email in any `emailAddress`, or malformed `body.contentType` (must be `"text"` or `"html"`) | Standard FastAPI/Pydantic validation error body |

---

## Postman collection setup checklist

- [ ] Environment variable `base_url` = `http://localhost:8000`
- [ ] Environment variable `access_token` — populate via the login request in §0, ideally with a Postman **Tests** script on the login request: `pm.environment.set("access_token", pm.response.json().access_token);`
- [ ] A Site Lead test user available for `/emails/dummy` testing (403 otherwise)
- [ ] At least one active `Client` row with a known `inbox_email` in your test database, to use as `to_email` (real transport) or `toRecipients[0].emailAddress.address` (Graph-shaped transport) — otherwise every inbound test returns `404 Unknown inbox address.`
- [ ] A known `client_id` for `/api/mail/outgoing` Option A requests
- [ ] Generate a fresh, unique `message_id`/`internetMessageId` per test run (e.g. a Postman pre-request script appending `{{$guid}}`) — reusing one across runs will trigger the `409` duplicate-detection path by design
