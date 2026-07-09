import json
from uuid import UUID

from fastapi import HTTPException, status
from shared_models.models import User

from app.models.permission_request import PermissionRequest, PermissionRequestStatus
from app.repositories import (
    PermissionRepository,
    PermissionRequestRepository,
    RolePermissionRepository,
    RoleRepository,
    UserRepository,
)
from app.schemas.audit_log import AuditLogCreate
from app.schemas.permission_override import GrantOverrideRequest
from app.schemas.permission_request import (
    PermissionRequestApprove,
    PermissionRequestCreate,
    PermissionRequestReject,
    PermissionRequestResponse,
)
from app.services.audit_log_service import AuditLogService
from app.services.permission_override_service import (
    UNRESTRICTED_OVERRIDE_ROLES,
    PermissionOverrideService,
)
from app.services.permission_resolver import PermissionResolverService

# A role can only ever be offered as an approver for a permission it
# already holds itself (can't vouch for something you don't have) and
# only if it has general override-granting authority in the first
# place — mirrors PermissionOverrideService.ensure_can_manage_overrides'
# own gate, just evaluated per-role instead of per-actor so it can
# populate a dropdown before anyone specific is chosen.
REQUIRED_GRANT_PERMISSION = "permission:override_grant"


class PermissionRequestService:
    """
    Self-service "ask for a permission you don't have" workflow,
    addressed to a role rather than a specific person — any user
    holding that role (and who'd actually pass
    PermissionOverrideService.ensure_can_manage_overrides for this
    requester) can review it. Approval doesn't grant anything itself;
    it delegates to the existing PermissionOverrideService.grant() so
    there's exactly one code path that ever creates a
    UserPermissionOverride row. Deliberately has no knowledge of
    ticketing-service's separate, ticket-scoped Edit Access workflow —
    the two are unrelated systems that happen to share the word
    "request".
    """

    def __init__(
        self,
        user_repository: UserRepository,
        role_repository: RoleRepository,
        permission_repository: PermissionRepository,
        role_permission_repository: RolePermissionRepository,
        permission_request_repository: PermissionRequestRepository,
        permission_override_service: PermissionOverrideService,
        permission_resolver: PermissionResolverService,
        audit_log_service: AuditLogService,
    ):
        self.user_repository = user_repository
        self.role_repository = role_repository
        self.permission_repository = permission_repository
        self.role_permission_repository = role_permission_repository
        self.permission_request_repository = permission_request_repository
        self.permission_override_service = permission_override_service
        self.permission_resolver = permission_resolver
        self.audit_log_service = audit_log_service

    # --------------------------------------------------
    # Eligible permissions / approver roles
    # --------------------------------------------------

    async def list_eligible_permissions(self, current_user: User):
        """Every catalog permission current_user doesn't already effectively hold."""

        all_permissions, _ = await self.permission_repository.get_all(
            page=1, page_size=1000
        )
        effective, _ = await self.permission_resolver.get_effective_permissions(
            current_user
        )
        effective_set = set(effective)

        return [p for p in all_permissions if p.permission_name not in effective_set]

    async def list_eligible_approver_roles(self, permission_id: UUID) -> list[str]:
        """
        Roles that both hold `permission:override_grant` and already
        hold the requested permission themselves — re-derived live
        against `role_permissions`, never against seed.py's static
        source, since a role's actual grants can drift from it (see
        CLAUDE.md).
        """

        permission = await self.permission_repository.get_by_id(permission_id)

        if permission is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Permission not found.",
            )

        roles, _ = await self.role_repository.get_all(page=1, page_size=100)
        eligible: list[str] = []

        for role in roles:
            role_permissions = (
                await self.role_permission_repository.get_permissions_by_role(
                    role.role_id
                )
            )
            role_permission_names = {p.permission_name for p in role_permissions}

            if (
                REQUIRED_GRANT_PERMISSION in role_permission_names
                and permission.permission_name in role_permission_names
            ):
                eligible.append(role.name)

        return eligible

    # --------------------------------------------------
    # Create
    # --------------------------------------------------

    async def create_request(
        self,
        current_user: User,
        request: PermissionRequestCreate,
    ) -> PermissionRequestResponse:

        permission = await self.permission_repository.get_by_id(
            request.permission_id
        )

        if permission is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Permission not found.",
            )

        effective, _ = await self.permission_resolver.get_effective_permissions(
            current_user
        )

        if permission.permission_name in effective:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="You already have this permission.",
            )

        eligible_roles = await self.list_eligible_approver_roles(request.permission_id)

        if request.requested_role not in eligible_roles:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="The selected role cannot grant this permission.",
            )

        existing = (
            await self.permission_request_repository.get_pending_by_requester_and_permission(
                current_user.user_id,
                request.permission_id,
            )
        )

        if existing is not None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="You already have a pending request for this permission.",
            )

        permission_request = await self.permission_request_repository.create(
            PermissionRequest(
                requester_id=current_user.user_id,
                permission_id=request.permission_id,
                requested_role=request.requested_role,
                reason=request.reason,
            )
        )

        await self.audit_log_service.create_log(
            AuditLogCreate(
                user_id=current_user.user_id,
                action="permission_request.create",
                entity_type="permission_request",
                entity_id=str(permission_request.request_id),
                new_value=json.dumps(
                    {
                        "permission_name": permission.permission_name,
                        "requested_role": request.requested_role,
                        "reason": request.reason,
                    }
                ),
            )
        )

        return await self._to_response(permission_request)

    # --------------------------------------------------
    # List
    # --------------------------------------------------

    async def list_mine(self, current_user: User) -> list[PermissionRequestResponse]:
        requests = await self.permission_request_repository.list_by_requester(
            current_user.user_id
        )

        return [await self._to_response(r) for r in requests]

    async def list_pending_for_review(
        self,
        current_user: User,
    ) -> list[PermissionRequestResponse]:
        """
        Super Admin/Site Lead (unconditional override authority) see
        every pending request regardless of which role it's addressed
        to; anyone else sees only requests addressed to their own
        role, further narrowed to requesters they'd actually pass
        PermissionOverrideService.ensure_can_manage_overrides for
        (e.g. an Account Manager only sees their own reports' requests).
        """

        if current_user.role.name in UNRESTRICTED_OVERRIDE_ROLES:
            requests = await self.permission_request_repository.list_pending_by_role(
                None
            )
        else:
            requests = await self.permission_request_repository.list_pending_by_role(
                current_user.role.name
            )

        visible: list[PermissionRequest] = []

        for permission_request in requests:
            requester = await self.user_repository.get_by_id(
                permission_request.requester_id
            )

            if requester is None:
                continue

            try:
                await self.permission_override_service.ensure_can_manage_overrides(
                    current_user, requester
                )
            except HTTPException:
                continue

            visible.append(permission_request)

        return [await self._to_response(r) for r in visible]

    # --------------------------------------------------
    # Approve
    # --------------------------------------------------

    async def approve(
        self,
        current_user: User,
        request_id: UUID,
        request: PermissionRequestApprove,
    ) -> PermissionRequestResponse:

        permission_request = await self.permission_request_repository.get_by_id(
            request_id
        )

        if permission_request is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Permission request not found.",
            )

        if permission_request.status != PermissionRequestStatus.PENDING:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="This request has already been reviewed.",
            )

        if (
            current_user.role.name != permission_request.requested_role
            and current_user.role.name not in UNRESTRICTED_OVERRIDE_ROLES
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="This request wasn't addressed to your role.",
            )

        # Delegates the actual authorization (permission:override_grant
        # + role scoping) and the grant itself to the existing,
        # already-tested override mechanism — this service never
        # creates a UserPermissionOverride row directly.
        override = await self.permission_override_service.grant(
            current_user,
            permission_request.requester_id,
            GrantOverrideRequest(
                permission_id=permission_request.permission_id,
                reason=permission_request.reason,
                expires_at=request.expires_at,
            ),
        )

        permission_request = await self.permission_request_repository.approve(
            permission_request,
            reviewed_by=current_user.user_id,
            review_comment=request.review_comment,
            expires_at=request.expires_at,
            granted_override_id=override.override_id,
        )

        await self.audit_log_service.create_log(
            AuditLogCreate(
                user_id=current_user.user_id,
                action="permission_request.approve",
                entity_type="permission_request",
                entity_id=str(permission_request.request_id),
                new_value=json.dumps(
                    {
                        "requester_id": str(permission_request.requester_id),
                        "override_id": str(override.override_id),
                        "expires_at": (
                            request.expires_at.isoformat()
                            if request.expires_at
                            else None
                        ),
                        "review_comment": request.review_comment,
                    }
                ),
            )
        )

        return await self._to_response(permission_request)

    # --------------------------------------------------
    # Reject
    # --------------------------------------------------

    async def reject(
        self,
        current_user: User,
        request_id: UUID,
        request: PermissionRequestReject,
    ) -> PermissionRequestResponse:

        permission_request = await self.permission_request_repository.get_by_id(
            request_id
        )

        if permission_request is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Permission request not found.",
            )

        if permission_request.status != PermissionRequestStatus.PENDING:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="This request has already been reviewed.",
            )

        if (
            current_user.role.name != permission_request.requested_role
            and current_user.role.name not in UNRESTRICTED_OVERRIDE_ROLES
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="This request wasn't addressed to your role.",
            )

        requester = await self.user_repository.get_by_id(
            permission_request.requester_id
        )

        if requester is not None:
            await self.permission_override_service.ensure_can_manage_overrides(
                current_user, requester
            )

        permission_request = await self.permission_request_repository.reject(
            permission_request,
            reviewed_by=current_user.user_id,
            review_comment=request.review_comment,
        )

        await self.audit_log_service.create_log(
            AuditLogCreate(
                user_id=current_user.user_id,
                action="permission_request.reject",
                entity_type="permission_request",
                entity_id=str(permission_request.request_id),
                new_value=json.dumps({"review_comment": request.review_comment}),
            )
        )

        return await self._to_response(permission_request)

    # --------------------------------------------------
    # Helpers
    # --------------------------------------------------

    async def _to_response(
        self,
        permission_request: PermissionRequest,
    ) -> PermissionRequestResponse:

        requester = await self.user_repository.get_by_id(
            permission_request.requester_id
        )
        reviewer = (
            await self.user_repository.get_by_id(permission_request.reviewed_by)
            if permission_request.reviewed_by is not None
            else None
        )

        revoked_at = (
            permission_request.granted_override.revoked_at
            if permission_request.granted_override is not None
            else None
        )

        return PermissionRequestResponse(
            request_id=permission_request.request_id,
            requester_id=permission_request.requester_id,
            requester_name=requester.name if requester is not None else None,
            permission_id=permission_request.permission_id,
            permission_name=permission_request.permission.permission_name,
            requested_role=permission_request.requested_role,
            reason=permission_request.reason,
            status=permission_request.status,
            reviewed_by=permission_request.reviewed_by,
            reviewed_by_name=reviewer.name if reviewer is not None else None,
            reviewed_at=permission_request.reviewed_at,
            review_comment=permission_request.review_comment,
            expires_at=permission_request.expires_at,
            granted_override_id=permission_request.granted_override_id,
            revoked_at=revoked_at,
            created_at=permission_request.created_at,
        )
