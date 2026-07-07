from fastapi import APIRouter

from app.api.v1.auth import router as auth_router
from app.api.v1.users import router as users_router
from app.api.v1.roles import router as roles_router
from app.api.v1.categories import router as categories_router
from app.api.v1.role_permissions import router as role_permissions_router
from app.api.v1.permissions import router as permissions_router
from app.api.v1.audit_logs import router as audit_logs_router

api_router = APIRouter()

api_router.include_router(auth_router)
api_router.include_router(users_router)
api_router.include_router(roles_router)
api_router.include_router(categories_router)
api_router.include_router(role_permissions_router)
api_router.include_router(permissions_router)
api_router.include_router(audit_logs_router)