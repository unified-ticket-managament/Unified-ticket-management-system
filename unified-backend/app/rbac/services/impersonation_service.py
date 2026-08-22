# impersonation_service.py

import json
from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import HTTPException, status
from shared_models.models import User

from app.auth.jwt import create_access_token, create_refresh_token
from app.core.config import get_settings
from app.rbac.models.impersonation_session import ImpersonationSession
from app.rbac.repositories.impersonation_session_repository import (
    ImpersonationSessionRepository,
)
from app.rbac.repositories.user_repository import UserRepository
from app.rbac.schemas.audit_log import AuditLogCreate
from app.rbac.schemas.impersonation import (
    ImpersonationStartResponse,
    ImpersonationTargetSummary,
)
from app.rbac.services.access_control import ensure_can_impersonate, ensure_has_permission
from app.rbac.services.audit_log_service import AuditLogService
from app.rbac.services.permission_resolver import PermissionResolverService

settings = get_settings()


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ImpersonationService:
    """
    "Login as User": a Super Admin (the actor) temporarily operates the
    app with a target user's identity/permissions — see this file's own
    plan doc (root CLAUDE.md's plans directory, if present) for the
    full design rationale. Two things make this safe:

    1. The minted access token's identity claims (role/permissions/
       scoped_permissions/category/categories/permission_version) are
       the TARGET's, computed fresh here exactly like a real login —
       never the actor's. This is what every existing authorization/
       visibility check in the app (both app.rbac's and app.ticketing's
       access_control.py) relies on to "just work" with zero changes.
    2. The actor's identity survives only as extra, additive JWT claims
       (impersonator_id/impersonator_name) that ONLY audit-writing code
       reads (via app.core.impersonation_context) — never anything
       that makes an authorization or visibility decision.
    """

    def __init__(
        self,
        user_repository: UserRepository,
        impersonation_session_repository: ImpersonationSessionRepository,
        permission_resolver: PermissionResolverService,
        audit_log_service: AuditLogService,
    ):
        self.user_repository = user_repository
        self.impersonation_session_repository = impersonation_session_repository
        self.permission_resolver = permission_resolver
        self.audit_log_service = audit_log_service

    # --------------------------------------------------
    # Start
    # --------------------------------------------------

    async def start(
        self,
        actor: User,
        target_user_id: UUID,
        ip_address: str | None = None,
    ) -> ImpersonationStartResponse:

        ensure_has_permission(actor, "user:impersonate")

        # Re-check against a fresh DB row, not the possibly-stale
        # rbac_cache-backed `actor` object get_current_active_user
        # handed us — a cache hit only proves "active as of up to
        # rbac_cache_ttl_seconds ago," and starting a brand-new
        # privileged session is exactly the kind of action that
        # shouldn't trust a stale cache.
        fresh_actor = await self.user_repository.get_by_id(actor.user_id)
        if fresh_actor is None or not fresh_actor.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Your account is inactive.",
            )

        if target_user_id == actor.user_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="You cannot impersonate yourself.",
            )

        if getattr(actor, "impersonation_session_id", None) is not None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="End your current impersonation session before starting another.",
            )

        target = await self.user_repository.get_by_id(target_user_id)
        if target is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found.",
            )

        ensure_can_impersonate(fresh_actor, target)

        if not target.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="This user account is inactive.",
            )

        permissions, _, scoped_permissions = (
            await self.permission_resolver.get_effective_permissions(target)
        )

        now = utc_now()
        expires_at = now + timedelta(minutes=settings.impersonation_max_minutes)

        session = await self.impersonation_session_repository.create(
            ImpersonationSession(
                actor_user_id=fresh_actor.user_id,
                target_user_id=target.user_id,
                started_at=now,
                expires_at=expires_at,
                status="ACTIVE",
            )
        )

        token_kwargs = dict(
            user_id=target.user_id,
            email=target.email,
            role=target.role.name,
            permissions=permissions,
            scoped_permissions=scoped_permissions,
            name=target.name,
            role_id=target.role_id,
            category_id=target.category_id,
            category=target.category.category_name if target.category else None,
            categories=[c.category_name for c in target.categories],
            permission_version=target.permission_version,
            impersonator_id=fresh_actor.user_id,
            impersonator_name=fresh_actor.name,
            impersonation_session_id=session.id,
        )

        access_token = create_access_token(
            expires_delta=expires_at - now,
            **token_kwargs,
        )
        refresh_token = create_refresh_token(
            user_id=target.user_id,
            expires_delta=expires_at - now,
            impersonation_session_id=session.id,
        )

        await self.audit_log_service.create_log(
            AuditLogCreate(
                user_id=fresh_actor.user_id,
                action="user_impersonation.started",
                entity_type="user",
                entity_id=str(target.user_id),
                new_value=json.dumps(
                    {
                        "session_id": str(session.id),
                        "target_name": target.name,
                        "target_role": target.role.name,
                        "expires_at": expires_at.isoformat(),
                    }
                ),
                ip_address=ip_address,
            )
        )

        return ImpersonationStartResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_at=expires_at,
            target_user=ImpersonationTargetSummary(
                user_id=target.user_id,
                name=target.name,
                role=target.role.name,
            ),
        )

    # --------------------------------------------------
    # End
    # --------------------------------------------------

    async def end(
        self,
        current_user: User,
        ip_address: str | None = None,
    ) -> None:
        """
        Called while still holding the impersonation-shaped access
        token — `current_user.user_id` at this point is the TARGET's
        id, not the actor's, so the actor's identity is read off the
        token's own `impersonator_id`/`impersonator_name` transient
        attributes (attached by app/dependencies/auth.py), never off
        `current_user.user_id` directly.
        """

        session_id = getattr(current_user, "impersonation_session_id", None)
        impersonator_id = getattr(current_user, "impersonator_id", None)
        impersonator_name = getattr(current_user, "impersonator_name", None)

        if session_id is None or impersonator_id is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No active impersonation session.",
            )

        session = await self.impersonation_session_repository.get_by_id(session_id)

        if session is None or session.status != "ACTIVE":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No active impersonation session.",
            )

        await self.impersonation_session_repository.end(session)

        await self.audit_log_service.create_log(
            AuditLogCreate(
                user_id=impersonator_id,
                action="user_impersonation.ended",
                entity_type="user",
                entity_id=str(current_user.user_id),
                new_value=json.dumps(
                    {
                        "session_id": str(session_id),
                        "impersonator_name": impersonator_name,
                        "target_name": current_user.name,
                    }
                ),
                ip_address=ip_address,
            )
        )
