from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.agent import router as agent_router
from app.api.attachment import router as attachment_router
from app.api.client import router as client_router
from app.api.email import router as email_router
from app.api.inbox import router as inbox_router
from app.api.interaction import router as interaction_router
from app.core.config import get_settings
from app.storage.base import StorageConfigurationError

from app.api.ticket import router as ticket_router
#backend/app/main.py
settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    version="1.0.0",
)

# ---------------------------------------------------------
# CORS
#
# Allows the React demo frontend (running on a different
# origin/port during development) to call this API. Without
# this, browsers block every cross-origin request after a
# failed OPTIONS preflight (405), even though the same
# request works fine from Swagger UI or curl.
# ---------------------------------------------------------
settings = get_settings()
origins = [
    origin.strip()
    for origin in settings.cors_origins.split(",")
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
        # Vite auto-increments to 5174+ if 5173 is already taken
        # by another running dev server — allow a small range so
        # an accidental second `npm run dev` doesn't look like a
        # broken backend (CORS-blocked calls surface to the user
        # as a generic "Network Error").
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------
# Routers
# ---------------------------------------------------------



app.include_router(email_router)

app.include_router(agent_router)

app.include_router(client_router)

app.include_router(inbox_router)

app.include_router(ticket_router)

app.include_router(interaction_router)

app.include_router(attachment_router)

# ---------------------------------------------------------
# Storage Misconfiguration
#
# A missing/incomplete STORAGE_BACKEND config (e.g. SUPABASE_URL /
# SUPABASE_SERVICE_ROLE_KEY not set on the deployed environment)
# would otherwise crash as an unhandled 500 — which some proxies
# return with no CORS headers, surfacing to the browser as an
# opaque "network error" instead of a readable message. Handling it
# here keeps the response inside FastAPI's normal (CORS-wrapped)
# response path.
# ---------------------------------------------------------


@app.exception_handler(StorageConfigurationError)
async def storage_configuration_error_handler(
    request: Request, exc: StorageConfigurationError
):
    return JSONResponse(status_code=503, content={"detail": str(exc)})


# ---------------------------------------------------------
# Health Check
# ---------------------------------------------------------

@app.get("/")
async def root():
    return {
        "message": "Ticket Management Backend Running"
    }


@app.get("/health")
async def health():
    return {
        "status": "healthy"
    }