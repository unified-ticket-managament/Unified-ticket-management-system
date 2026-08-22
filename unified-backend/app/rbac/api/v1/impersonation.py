from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies.auth import get_current_active_user
from app.database.session import get_db
from app.rbac.repositories.audit_log_repository import AuditLogRepository
from app.rbac.repositories.impersonation_session_repository import (
    ImpersonationSessionRepository,
)
from app.rbac.repositories.permission_override_repository import (
    PermissionOverrideRepository,
)
from app.rbac.repositories.role_permission_repository import RolePermissionRepository
from app.rbac.repositories.user_repository import UserRepository
from app.rbac.schemas.impersonation import (
    ImpersonationStartRequest,
    ImpersonationStartResponse,
)
from app.rbac.services.audit_log_service import AuditLogService
from app.rbac.services.impersonation_service import ImpersonationService
from app.rbac.services.permission_resolver import PermissionResolverService

router = APIRouter(
    prefix="/admin/impersonation",
    tags=["Impersonation"],
)


# --------------------------------------------------
# Dependency
# --------------------------------------------------


def get_impersonation_service(
    db: AsyncSession = Depends(get_db),
) -> ImpersonationService:
    user_repository = UserRepository(db)
    role_permission_repository = RolePermissionRepository(db)
    permission_override_repository = PermissionOverrideRepository(db)

    permission_resolver = PermissionResolverService(
        role_permission_repository=role_permission_repository,
        permission_override_repository=permission_override_repository,
    )

    audit_log_service = AuditLogService(
        audit_log_repository=AuditLogRepository(db),
    )

    return ImpersonationService(
        user_repository=user_repository,
        impersonation_session_repository=ImpersonationSessionRepository(db),
        permission_resolver=permission_resolver,
        audit_log_service=audit_log_service,
    )


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


# --------------------------------------------------
# Start
# --------------------------------------------------


@router.post(
    "/start",
    response_model=ImpersonationStartResponse,
    status_code=status.HTTP_200_OK,
    summary="Start Impersonation (Login as User)",
)
async def start_impersonation(
    body: ImpersonationStartRequest,
    request: Request,
    current_user=Depends(get_current_active_user),
    service: ImpersonationService = Depends(get_impersonation_service),
):
    """
    Requires `user:impersonate` (Super Admin by default). Mints a
    time-bounded token pair carrying the target's identity/permissions
    — see ImpersonationService.start's own docstring.
    """

    return await service.start(
        current_user,
        body.target_user_id,
        ip_address=_client_ip(request),
    )


# --------------------------------------------------
# End
# --------------------------------------------------


@router.post(
    "/end",
    status_code=status.HTTP_200_OK,
    summary="End Impersonation",
)
async def end_impersonation(
    request: Request,
    current_user=Depends(get_current_active_user),
    service: ImpersonationService = Depends(get_impersonation_service),
):
    """
    Must be called while still holding the impersonation-shaped access
    token. Marks the session ended server-side (so it can never be
    used again even if its JWT `exp` hasn't been reached yet) — the
    frontend is responsible for restoring the admin's own, separately
    retained tokens afterward; this endpoint doesn't return new ones.
    """

    await service.end(current_user, ip_address=_client_ip(request))

    return {"message": "Impersonation session ended."}
