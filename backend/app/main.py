from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.api_router import api_router
from app.core.config import get_settings

settings = get_settings()


# --------------------------------------------------
# Application Lifespan
# --------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application startup and shutdown events.
    """

    print("Starting RBAC Service...")

    yield

    print("Stopping RBAC Service...")


# --------------------------------------------------
# FastAPI Application
# --------------------------------------------------


app = FastAPI(
    title="RBAC Service",
    description="Role Based Access Control Service",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)


# --------------------------------------------------
# CORS
# --------------------------------------------------


app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --------------------------------------------------
# Root Endpoint
# --------------------------------------------------


@app.get("/", tags=["Root"])
async def root():
    return {
        "message": "RBAC Service is running.",
        "docs": "/docs",
    }


# --------------------------------------------------
# Health Check
# --------------------------------------------------


@app.get("/health", tags=["Health"])
async def health_check():
    return {
        "status": "healthy",
        "service": "RBAC Service",
    }


# --------------------------------------------------
# API Routes
# --------------------------------------------------


app.include_router(
    api_router,
    prefix="/api/v1",
)