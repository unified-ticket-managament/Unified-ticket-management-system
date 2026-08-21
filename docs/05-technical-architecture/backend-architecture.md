# Backend Architecture

## App assembly (`app/main.py`)

- `FastAPI(title=settings.app_name, version="1.0.0", lifespan=lifespan, docs_url="/docs", redoc_url="/redoc", openapi_url="/openapi.json")`, built at import time from a module-level `settings = get_settings()`.
- **Middleware**, added in this order:
  1. `CORSMiddleware` — `allow_origins=settings.cors_origins_list`, `allow_credentials=True`, `allow_methods=["*"]`, `allow_headers=["*"]`, exposes `X-Total-Count`/`X-Next-Cursor`/`Server-Timing`.
  2. `ServerTimingMiddleware` — a custom **raw ASGI** middleware (deliberately not Starlette's `BaseHTTPMiddleware`, which runs the route in a separate asyncio Task and would break ContextVar-based DB-timing propagation). Emits a `Server-Timing` header with `total`, `db`, and any named stages (e.g. `auth`).
- **Lifespan** (`asynccontextmanager`): starts/stops the SLA scheduler, the Graph subscription scheduler, and the Graph mail-poll scheduler, in that order (and the reverse on shutdown).
- **Exception handler**: `StorageConfigurationError` → clean 503 (with CORS headers intact — see [16-known-limitations](../16-known-limitations/README.md) for why this matters, given the "unhandled 500 looks like CORS" pattern seen elsewhere).
- **Router mounting**: `rbac_api_router` at `/api/v1`; every ticketing router unprefixed (each carries its own `prefix=`); `notifications_router` unprefixed (declares its own `/notifications` prefix). Full endpoint list: [07-api](../07-api/README.md).

## Configuration (`app/core/config.py`)

`Settings` (pydantic-settings `BaseSettings`, reads `.env`, case-insensitive, `extra="ignore"`), cached via `@lru_cache` — **editing `.env` while the process is running has no effect until restart**. See [configuration.md](configuration.md) for the full field list.

`database_url`'s `field_validator(mode="before")` rewrites `postgres://`/`postgresql://` → `postgresql+asyncpg://`, renames libpq's `sslmode` to asyncpg's `ssl`, and strips `channel_binding` — required because Neon hands out libpq-style connection strings.

## Session cache (`app/core/rbac_cache.py`)

`RBACCache` — thread-safe (`threading.Lock`), TTL + LRU (`OrderedDict`), keyed on `(user_id, permission_version)`. `resolution_lock(user_id)` (an async-lock-per-user dict, created/removed on demand) serializes concurrent cache-miss resolution, preventing a stampede of simultaneous DB lookups for the same user.

## Shared auth dependency (`app/dependencies/auth.py`)

`_authenticate_token` is the one function both `get_current_user` (header-based) and `get_current_user_sse` (query-param-based, its own short-lived DB session) route through. On a cache hit, `_build_transient_user` reconstructs a `User`/`Role`/`Category` purely from JWT claims — zero DB round trips. `AGENT_ROLE_NAMES`/`SUPERVISOR_ROLE_NAMES` (and the rest of the ticketing-domain role-name constants) are actually defined in `app/ticketing/services/access_control.py`, imported from there — not duplicated in the auth dependency file itself.

## Database session (`app/database/session.py`)

`create_async_engine(..., pool_size=20, max_overflow=30, pool_timeout=10, pool_recycle=1800, pool_pre_ping=True)` — raised from an original 10/20 after a frontend request-duplication bug queued 200-300 concurrent requests and hit the SQLAlchemy default 30s timeout. `AsyncSessionLocal` is `expire_on_commit=False` — this is what lets background tasks (email dispatch) keep referencing already-committed ORM objects safely.

## The two domains, side by side

| | `app/rbac/` | `app/ticketing/` |
|---|---|---|
| API routers | 10 files | 13 files |
| Services | 12 files | 30 files |
| Repositories | 10 files | 16 files |
| Models | 9 files (3 re-exported from `shared_models`) | 17 files |
| Mounted at | `/api/v1` | unprefixed |
| JWT role | Issuer | Verify-only consumer |
| Authorization enforcement | Historically thin, partially hardened by a 2026 audit | Real, throughout `access_control.py` |

## Postgres-native enums (backend-defined)

`TicketStatus`/`TicketPriority` (`ticket_enums.py`), `SLAClockStatus` (`sla_enums.py`), `EscalationLevel`/`EscalationStatus` (`escalation_enums.py`), `AuditEventType`/`AuditEntityType`/`ActorRole` (`audit_enums.py`), `InteractionStatus`/`InteractionDirection` (`interaction_enums.py`). `RuleCategory` and `NotificationType` are deliberately **plain string constants**, not DB enums — chosen so extending them never requires a migration. See [06-database/README.md](../06-database/README.md).

**`Category.category_name` was moved from this "native enum" list to the plain-string list on 2026-08-21** — the `CategoryName` Python enum and its backing `category_name_enum` Postgres type were both removed (migration `a4c6e8b0d2f5`); categories are now created dynamically at runtime through `POST /categories`, with no migration required per new category. This reverses the original design tradeoff for this one column specifically — see [15-architecture-decisions/ADR-001-database-architecture.md](../15-architecture-decisions/ADR-001-database-architecture.md) if extending this ADR to cover the reversal.

## Semantic OTP classification (new, 2026-08-21)

`app/ticketing/services/otp_classifier.py`'s `classify_otp_email(subject, body, *, threshold) -> OTPClassificationResult` is a pure, dependency-free heuristic text scorer (regex/weighted-pattern based — **not** a machine-learning model and **not** a call to any external NLP/LLM API; a codebase-wide scan confirmed no such dependency exists or was added) that decides whether an inbound email is a genuine one-time-passcode delivery versus merely *mentioning* "OTP" (e.g. a support complaint). It replaces keyword-based Mail Rule matching as the trigger for completing the First Response SLA clock — see [03-business-workflows/communication/email-processing.md](../03-business-workflows/communication/email-processing.md) for the full mechanics and [configuration.md](configuration.md) for its one runtime setting, `OTP_NLP_CONFIDENCE_THRESHOLD`.

## Microsoft Graph integration internals

See [02-system-architecture/integration-architecture.md](../02-system-architecture/integration-architecture.md) and [03-business-workflows/communication/incoming-email.md](../03-business-workflows/communication/incoming-email.md) for the full flow. Key files: `graph_auth.py` (MSAL), `graph_client.py` (fetch/send), `graph_subscription_service.py` (webhook lifecycle), `graph_mail_poller.py` (polling fallback), `mail_mapping_service.py` (payload translation), `mail_provider.py` (real-vs-mock factory).
