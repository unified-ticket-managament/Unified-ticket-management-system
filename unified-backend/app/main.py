from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.config import get_settings
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
from app.ticketing.api.ticket import router as ticketing_ticket_router
from app.ticketing.storage.base import StorageConfigurationError

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("Starting Unified Backend (RBAC + Ticketing)...")
    yield
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
)

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
app.include_router(ticketing_ticket_router)
app.include_router(ticketing_interaction_router)
app.include_router(ticketing_attachment_router)

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
