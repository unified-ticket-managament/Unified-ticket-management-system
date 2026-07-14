import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.datastructures import MutableHeaders

from app.core.config import get_settings
from app.core.request_timing import get_stage_times, reset_stage_times
from app.core.sla_scheduler import shutdown_scheduler, start_scheduler
from app.database.timing import get_db_time_ms, reset_db_time
from app.notifications.routes import router as notifications_router
from app.rbac.api.v1.api_router import api_router as rbac_api_router
from app.ticketing.api.agent import router as ticketing_agent_router
from app.ticketing.api.attachment import router as ticketing_attachment_router
from app.ticketing.api.category import router as ticketing_category_router
from app.ticketing.api.client import router as ticketing_client_router
from app.ticketing.api.email import router as ticketing_email_router
from app.ticketing.api.inbox import router as ticketing_inbox_router
from app.ticketing.api.interaction import router as ticketing_interaction_router
from app.ticketing.api.mail_folder import router as ticketing_mail_folder_router
from app.ticketing.api.mail_integration import router as ticketing_mail_integration_router
from app.ticketing.api.sla import ticket_sla_router as ticketing_sla_ticket_router
from app.ticketing.api.sla import sla_policy_router as ticketing_sla_policy_router
from app.ticketing.api.sla_internal import router as ticketing_sla_internal_router
from app.ticketing.api.ticket import router as ticketing_ticket_router
from app.ticketing.storage.base import StorageConfigurationError

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("Starting Unified Backend (RBAC + Ticketing)...")
    start_scheduler()
    yield
    shutdown_scheduler()
    print("Stopping Unified Backend...")


app = FastAPI(
    title=settings.app_name,
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)

# ---------------------------------------------------------
# CORS
# ---------------------------------------------------------

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    # Custom response headers are otherwise invisible to browser JS on
    # a cross-origin request (unified-frontend on :3000 calling this
    # on :8000) — X-Total-Count backs paginated list endpoints (e.g.
    # GET /tickets/interactions, GET /inbox) that report a filtered
    # total alongside a bounded page of items.
    expose_headers=["X-Total-Count", "X-Next-Cursor", "Server-Timing"],
)

# ---------------------------------------------------------
# Server-Timing
#
# Two phases: `total` (the whole request) and `db` (cumulative time
# spent inside DB cursor execution, via SQLAlchemy engine events — see
# app/database/timing.py). `total - db` is everything else (auth
# dependency, enrichment/serialization, network). This is the one
# phase split that's actually cheap and low-risk to add: it hooks the
# engine once, centrally, rather than threading timers through every
# service/route — which is exactly why a full auth/query/enrichment/
# serialization breakdown (a separate timer at every layer, in every
# route) remains out of scope: that would need touching every service
# module for a granularity this session's actual investigations never
# needed (EXPLAIN ANALYZE + this total/db split already answered every
# "is this the backend or the network/frontend, and is it the DB or
# app-side" question that came up). No existing timing/logging
# middleware was in place before this.
#
# Deliberately a raw ASGI middleware, not `@app.middleware("http")`.
# The latter is Starlette's BaseHTTPMiddleware, which runs the actual
# route handler in a *separate* asyncio Task (to support streaming
# responses) — asyncio Tasks get their own copy of the contextvars
# Context, and mutations inside a child Task never propagate back to
# the parent, so `db_time_ms` always read back as 0 from the parent
# Task even though the DB events were firing correctly. A raw ASGI
# middleware runs the whole downstream app in the same Task, so the
# ContextVar set here is the same one the DB event listeners mutate.
# ---------------------------------------------------------


class ServerTimingMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        reset_db_time()
        reset_stage_times()
        start = time.perf_counter()

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                duration_ms = (time.perf_counter() - start) * 1000
                db_ms = get_db_time_ms()
                stages = get_stage_times()
                entries = [f"total;dur={duration_ms:.1f}", f"db;dur={db_ms:.1f}"]
                entries.extend(f"{name};dur={dur:.1f}" for name, dur in stages.items())
                headers = MutableHeaders(scope=message)
                headers.append("Server-Timing", ", ".join(entries))
            await send(message)

        await self.app(scope, receive, send_wrapper)


app.add_middleware(ServerTimingMiddleware)


# ---------------------------------------------------------
# Routers
#
# Every existing route path stays byte-identical to the two
# standalone services: RBAC's own routers already carry their own
# sub-prefixes and are mounted here under /api/v1 exactly as before;
# Ticketing's routers already carry their own prefixes too and are
# mounted unprefixed, exactly as before.
# ---------------------------------------------------------

app.include_router(rbac_api_router, prefix="/api/v1")

app.include_router(notifications_router)

app.include_router(ticketing_email_router)
app.include_router(ticketing_agent_router)
app.include_router(ticketing_client_router)
app.include_router(ticketing_category_router)
app.include_router(ticketing_inbox_router)
app.include_router(ticketing_mail_folder_router)
app.include_router(ticketing_mail_integration_router)
app.include_router(ticketing_ticket_router)
app.include_router(ticketing_interaction_router)
app.include_router(ticketing_attachment_router)
app.include_router(ticketing_sla_ticket_router)
app.include_router(ticketing_sla_policy_router)
app.include_router(ticketing_sla_internal_router)

# ---------------------------------------------------------
# Storage Misconfiguration
#
# A missing/incomplete STORAGE_BACKEND config would otherwise crash
# as an unhandled 500 with no CORS headers on some proxies, surfacing
# to the browser as an opaque "network error" instead of a readable
# message. Handling it here keeps the response inside FastAPI's
# normal (CORS-wrapped) response path.
# ---------------------------------------------------------


@app.exception_handler(StorageConfigurationError)
async def storage_configuration_error_handler(
    request: Request, exc: StorageConfigurationError
):
    return JSONResponse(status_code=503, content={"detail": str(exc)})


# ---------------------------------------------------------
# Root / Health
# ---------------------------------------------------------


@app.get("/", tags=["Root"])
async def root():
    return {"message": "Unified Backend is running.", "docs": "/docs"}


@app.get("/health", tags=["Health"])
async def health():
    return {"status": "healthy"}
