from fastapi import FastAPI

from app.api.agent import router as agent_router
from app.api.email import router as email_router
from app.core.config import get_settings

from app.api.ticket import router as ticket_router

settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    version="1.0.0",
)

# ---------------------------------------------------------
# Routers
# ---------------------------------------------------------

app.include_router(email_router)
app.include_router(agent_router)

app.include_router(email_router)

app.include_router(agent_router)

app.include_router(ticket_router)

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