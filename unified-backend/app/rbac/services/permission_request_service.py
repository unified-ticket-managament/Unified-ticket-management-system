import json
from uuid import UUID

from fastapi import HTTPException, status
from shared_models.models import User

from app.rbac.models.permission_request import PermissionRequest, PermissionRequestStatus
from app.rbac.repositories import (
    PermissionRepository,
    PermissionRequestRepository,
    RolePermissionRepository,
    RoleRepository,
    UserRepository,
)
from app.rbac.schemas.audit_log import AuditLogCreate
from app.rbac.schemas.permission_override import GrantOverrideRequest
from app.rbac.schemas.permission_request import (
    PermissionRequestApprove,
    PermissionRequestCreate,
    PermissionRequestReject,
    PermissionRequestResponse,
    PermissionRequestRevoke,
)
from app.rbac.services.audit_log_service import AuditLogService
from app.rbac.services.permission_override_service import (
    SCOPED_OVERRIDE_ROLE,
    UNRESTRICTED_OVERRIDE_ROLES,
    PermissionOverrideService,
)
from app.rbac.services.permission_resolver import PermissionResolverService
from app.notifications.service import NotificationService, NotificationType

# A role can only ever be offered as an approver for a permission it
# already holds itself (can't vouch for something you don't have) and
# only if it has general override-granting authority in the first
# place — mirrors PermissionOverrideService.ensure_can_manage_overrides'
# own gate, just evaluated per-role instead of per-actor so it can
# populate a dropdown before anyone specific is chosen.
REQUIRED_GRANT_PERMISSION = "permission:override_grant"

# Super Admin holds every permission by default (see seed.py) — there
# is never a real permission for them to ask for, so request creation
# is blocked outright rather than left to fail on the "already have
# this permission" check below, which would only catch it as long as
# seed data stays exhaustive.
SUPER_ADMIN_ROLE = "Super Admin"


class PermissionRequestService:
    """
    Self-service "ask for a permission you don't have" workflow,
    addressed to one specific person (selected_approver_id) rather
    than broadcast to a role — only that exact user is notified, sees
    it in "Pending My Review", and can approve/reject it. requested_role
    is kept purely as an immutable display snapshot of the approver's
    role at request time (list_eligible_approver_users still groups
    candidates by role so the picker can label them), never itself an
    authorization boundary. Approval doesn't grant anything itself; it
    delegates to the existing PermissionOverrideService.grant() so
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
        notification_service: NotificationService | None = None,
        ticket_repository=None,
    ):
        self.user_repository = user_repository
        self.role_repository = role_repository
        self.permission_repository = permission_repository
        self.role_permission_repository = role_permission_repository
        self.permission_request_repository = permission_request_repository
        self.permission_override_service = permission_override_service
        self.permission_resolver = permission_resolver
        self.audit_log_service = audit_log_service
        self.notification_service = notification_service
        # Optional: only needed for the ticket-scoped editother_ticket
        # flow (validating/looking up a teammate's ticket) — a plain
        # attribute rather than a typed import so this rbac-domain
        # service doesn't have to hard-depend on ticketing's module at
        # import time; the router wires the real TicketRepository in.
        self.ticket_repository = ticket_repository

    # --------------------------------------------------
    # Ticket-scoped editother_ticket helpers
    # --------------------------------------------------

    async def _is_teammate(self, requester: User, other_user_id: UUID) -> bool:
        """
        "Teammate" = another Staff member reporting to the same Team
        Lead — mirrors the org-chart's own teamlead_id grouping rather
        than inventing a new notion of team.
        """

        if requester.teamlead_id is None or other_user_id == requester.user_id:
            return False

        other = await self.user_repository.get_by_id(other_user_id)

        return other is not None and other.teamlead_id == requester.teamlead_id

    async def list_teammate_staff(self, current_user: User) -> list[User]:
        """Other Staff sharing current_user's Team Lead — populates the
        "Select Staff" dropdown for a ticket-scoped editother_ticket
        request. Empty for anyone with no teamlead_id (including
        anyone who isn't Staff)."""

        if current_user.teamlead_id is None:
            return []

        teammates = await self.user_repository.get_by_teamlead(current_user.teamlead_id)

        return [u for u in teammates if u.user_id != current_user.user_id]

    async def list_teammate_tickets(self, current_user: User, staff_id: UUID) -> list:
        """Tickets assigned to a specific teammate — populates the
        "Select Ticket" dropdown, once a teammate is chosen. Raises if
        staff_id isn't actually a teammate, so this can't be used to
        probe an arbitrary user's ticket list."""

        if not await self._is_teammate(current_user, staff_id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You can only see tickets for your own teammates.",
            )

        if self.ticket_repository is None:
            return []

        # list_all(agent_id=...) deliberately also returns unassigned
        # tickets (shared-pool visibility) — not wanted here, so filter
        # to tickets actually assigned to this teammate.
        tickets, _ = await self.ticket_repository.list_all(agent_id=staff_id)
        return [t for t in tickets if t.agent_id == staff_id]

    async def _resolve_approver_candidates(
        self, requester_id: UUID, eligible_roles: list[str]
    ) -> list[tuple[User, str]]:
        """
        Turns "roles eligible to approve" (list_eligible_approver_roles,
        role names only) into the actual (user, role_name) candidates a
        requester may pick as their specific approver — unrestricted
        for Super Admin/Site Lead, scoped to "is this requester one of
        their own reports" for Account Manager (mirroring
        ensure_can_manage_overrides' own scoping), unrestricted as a
        safe fallback for any other role list_eligible_approver_roles
        might someday return. This is the one place that set of
        candidates is computed — both the "Request To" picker
        (list_eligible_approver_users) and create_request's own
        server-side validation of the submitted selected_approver_id
        call through here, so a client can never submit an approver
        outside what they were actually shown.
        """

        candidates: dict[UUID, tuple[User, str]] = {}

        for role_name in eligible_roles:
            role_candidates = await self.user_repository.list_active_by_role_name(role_name)

            if role_name == SCOPED_OVERRIDE_ROLE:
                for candidate in role_candidates:
                    subordinate_ids = (
                        await self.permission_override_service.organization_service.get_subordinate_user_ids(
                            candidate
                        )
                    )
                    if requester_id in subordinate_ids:
                        candidates[candidate.user_id] = (candidate, role_name)
            else:
                for candidate in role_candidates:
                    candidates[candidate.user_id] = (candidate, role_name)

        candidates.pop(requester_id, None)

        return list(candidates.values())

    async def list_eligible_approver_users(
        self, permission_id: UUID, current_user: User
    ) -> list[tuple[User, str]]:
        """Populates the "Request To" picker: the real, specific people
        current_user may address this request to for a given
        permission — never a role name, so notification/review access
        is unambiguous from the moment the request is created."""

        eligible_roles = await self.list_eligible_approver_roles(permission_id)

        return await self._resolve_approver_candidates(
            current_user.user_id, eligible_roles
        )

    # --------------------------------------------------
    # Eligible permissions / approver roles
    # --------------------------------------------------

    async def list_eligible_permissions(self, current_user: User):
        """Every catalog permission current_user doesn't already effectively hold."""

        all_permissions, _ = await self.permission_repository.get_all(
            page=1, page_size=1000
        )
        effective, _, _ = await self.permission_resolver.get_effective_permissions(
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

        if current_user.role.name == SUPER_ADMIN_ROLE:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Super Admin already has every permission and cannot create permission requests.",
            )

        permission = await self.permission_repository.get_by_id(
            request.permission_id
        )

        if permission is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Permission not found.",
            )

        effective, _, _ = await self.permission_resolver.get_effective_permissions(
            current_user
        )

        if permission.permission_name in effective:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="You already have this permission.",
            )

        if request.scope_ticket_id is not None:
            ticket = await self.ticket_repository.get_by_id(request.scope_ticket_id)
            if ticket is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Ticket not found.",
                )
            if ticket.agent_id is None or not await self._is_teammate(
                current_user, ticket.agent_id
            ):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="You can only request access to a teammate's ticket.",
                )

        eligible_roles = await self.list_eligible_approver_roles(request.permission_id)
        candidates = await self._resolve_approver_candidates(
            current_user.user_id, eligible_roles
        )
        candidates_by_id = {u.user_id: (u, role_name) for u, role_name in candidates}

        if request.selected_approver_id not in candidates_by_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="The selected user cannot approve this request.",
            )

        selected_approver, approver_role_name = candidates_by_id[request.selected_approver_id]

        existing = (
            await self.permission_request_repository.get_pending_by_requester_permission_and_scope(
                current_user.user_id,
                request.permission_id,
                request.scope_ticket_id,
            )
        )

        if existing is not None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="This permission request is already pending approval.",
            )

        permission_request = await self.permission_request_repository.create(
            PermissionRequest(
                requester_id=current_user.user_id,
                permission_id=request.permission_id,
                requested_role=approver_role_name,
                selected_approver_id=selected_approver.user_id,
                reason=request.reason,
                scope_ticket_id=request.scope_ticket_id,
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
                        "requester_id": str(current_user.user_id),
                        "selected_approver_id": str(selected_approver.user_id),
                        "permission_name": permission.permission_name,
                        "requested_role": approver_role_name,
                        "reason": request.reason,
                        "scope_ticket_id": (
                            str(request.scope_ticket_id)
                            if request.scope_ticket_id
                            else None
                        ),
                        "previous_status": None,
                        "new_status": PermissionRequestStatus.PENDING,
                    }
                ),
            )
        )

        if self.notification_service is not None:
            # Exactly one recipient — the specific person selected, not
            # a role broadcast. No other Site Lead/Account Manager/
            # Super Admin/etc. is ever notified about this request.
            await self.notification_service.notify(
                selected_approver.user_id,
                NotificationType.PERMISSION_REQUESTED,
                title=f"{current_user.name} requested a permission",
                message=f"{permission.permission_name}",
                link="/permission-requests",
                related_entity_type="permission_request",
                related_entity_id=permission_request.request_id,
            )

        return await self._to_response(permission_request, current_user)

    # --------------------------------------------------
    # List
    # --------------------------------------------------

    async def list_mine(self, current_user: User) -> list[PermissionRequestResponse]:
        requests = await self.permission_request_repository.list_by_requester(
            current_user.user_id
        )

        return [await self._to_response(r, current_user) for r in requests]

    async def list_pending_for_review(
        self,
        current_user: User,
    ) -> list[PermissionRequestResponse]:
        """
        Strictly requests where current_user is the selected approver
        — no role or subordinate-scoping logic, since that's now
        exactly what selected_approver_id already encodes. Once a
        request is decided (approved/rejected) it moves to History
        instead of lingering here.
        """

        requests = await self.permission_request_repository.list_pending_for_approver(
            current_user.user_id
        )

        return [await self._to_response(r, current_user) for r in requests]

    async def list_history(
        self,
        current_user: User,
    ) -> list[PermissionRequestResponse]:
        """
        Every decided request (APPROVED/REJECTED/REVOKED) — a broader
        oversight view than "Pending My Review", available to whoever
        holds general override-managing authority (Super Admin/Site
        Lead unrestricted, Account Manager narrowed to their own
        reports via the same PermissionOverrideService.
        ensure_can_manage_overrides scoping the old role-based review
        queue used), not just requests addressed to current_user
        personally.
        """

        requests = await self.permission_request_repository.list_history()

        if current_user.role.name in UNRESTRICTED_OVERRIDE_ROLES:
            visible = requests
        else:
            visible = []
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

        return [await self._to_response(r, current_user) for r in visible]

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

        if current_user.user_id != permission_request.selected_approver_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="This request wasn't addressed to you.",
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
                scope_ticket_id=permission_request.scope_ticket_id,
            ),
            # This method sends its own PERMISSION_APPROVED notification
            # below — grant()'s own PERMISSION_GRANTED would otherwise
            # fire a second, duplicate notification for this same event.
            notify=False,
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
                        "selected_approver_id": str(current_user.user_id),
                        "permission_name": permission_request.permission.permission_name,
                        "override_id": str(override.override_id),
                        "expires_at": (
                            request.expires_at.isoformat()
                            if request.expires_at
                            else None
                        ),
                        "review_comment": request.review_comment,
                        "previous_status": PermissionRequestStatus.PENDING,
                        "new_status": PermissionRequestStatus.APPROVED,
                    }
                ),
            )
        )

        if self.notification_service is not None:
            await self.notification_service.notify(
                permission_request.requester_id,
                NotificationType.PERMISSION_APPROVED,
                title="Your permission request was approved",
                message=f"{permission_request.permission.permission_name} (as {permission_request.requested_role})",
                link="/permission-requests",
                related_entity_type="permission_request",
                related_entity_id=permission_request.request_id,
            )

        return await self._to_response(permission_request, current_user)

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

        if current_user.user_id != permission_request.selected_approver_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="This request wasn't addressed to you.",
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
                new_value=json.dumps(
                    {
                        "requester_id": str(permission_request.requester_id),
                        "selected_approver_id": str(current_user.user_id),
                        "permission_name": permission_request.permission.permission_name,
                        "review_comment": request.review_comment,
                        "previous_status": PermissionRequestStatus.PENDING,
                        "new_status": PermissionRequestStatus.REJECTED,
                    }
                ),
            )
        )

        if self.notification_service is not None:
            await self.notification_service.notify(
                permission_request.requester_id,
                NotificationType.PERMISSION_REJECTED,
                title="Your permission request was rejected",
                message=f"{permission_request.permission.permission_name} (as {permission_request.requested_role})",
                link="/permission-requests",
                related_entity_type="permission_request",
                related_entity_id=permission_request.request_id,
            )

        return await self._to_response(permission_request, current_user)

    # --------------------------------------------------
    # Revoke
    # --------------------------------------------------

    def _can_revoke(self, current_user: User, permission_request: PermissionRequest) -> bool:
        """Only the original approver, or Super Admin, may revoke —
        no exception, mirrors the acknowledge/confirm-assignment
        pattern elsewhere in this codebase of a strict, non-bypassable
        ownership check rather than a broad role allowlist."""

        if permission_request.status != PermissionRequestStatus.APPROVED:
            return False

        return (
            current_user.role.name == SUPER_ADMIN_ROLE
            or current_user.user_id == permission_request.reviewed_by
        )

    async def revoke(
        self,
        current_user: User,
        request_id: UUID,
        request: PermissionRequestRevoke,
    ) -> PermissionRequestResponse:

        permission_request = await self.permission_request_repository.get_by_id(
            request_id
        )

        if permission_request is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Permission request not found.",
            )

        if permission_request.status != PermissionRequestStatus.APPROVED:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Only an approved request can be revoked.",
            )

        if not self._can_revoke(current_user, permission_request):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only the original approver or Super Admin can revoke this permission.",
            )

        permission_name = permission_request.permission.permission_name
        requester_id = permission_request.requester_id
        scope_ticket_id = permission_request.scope_ticket_id

        # Delegates the actual permission removal (and the live-session
        # refresh via permission_version) to the existing, already-
        # tested override mechanism — this never mutates the override
        # row directly. granted_override_id is only ever unset if the
        # override itself was already revoked out-of-band through the
        # Users > Permission Overrides screen; either way the request's
        # own status still needs to move to REVOKED.
        if permission_request.granted_override_id is not None:
            await self.permission_override_service.revoke(
                current_user,
                requester_id,
                permission_request.granted_override_id,
                # This method sends its own PERMISSION_REVOKED
                # notification below — revoke()'s own would otherwise
                # duplicate it for this same event.
                notify=False,
            )

        permission_request = await self.permission_request_repository.revoke(
            permission_request,
            revoked_by=current_user.user_id,
            revoke_reason=request.reason,
        )

        await self.audit_log_service.create_log(
            AuditLogCreate(
                user_id=current_user.user_id,
                action="permission_request.revoke",
                entity_type="permission_request",
                entity_id=str(permission_request.request_id),
                old_value=json.dumps(
                    {
                        "requester_id": str(requester_id),
                        "permission_name": permission_name,
                        "scope_ticket_id": (
                            str(scope_ticket_id) if scope_ticket_id else None
                        ),
                    }
                ),
                new_value=json.dumps(
                    {
                        "revoked_by": str(current_user.user_id),
                        "revoked_at": permission_request.revoked_at.isoformat(),
                        "reason": request.reason,
                        "previous_status": PermissionRequestStatus.APPROVED,
                        "new_status": PermissionRequestStatus.REVOKED,
                    }
                ),
            )
        )

        if self.notification_service is not None:
            await self.notification_service.notify(
                requester_id,
                NotificationType.PERMISSION_REVOKED,
                title="A granted permission was revoked",
                message=f"{permission_name} (as {permission_request.requested_role})",
                link="/permission-requests",
                related_entity_type="permission_request",
                related_entity_id=permission_request.request_id,
            )

        return await self._to_response(permission_request, current_user)

    # --------------------------------------------------
    # Helpers
    # --------------------------------------------------

    async def _to_response(
        self,
        permission_request: PermissionRequest,
        current_user: User | None = None,
    ) -> PermissionRequestResponse:

        requester = await self.user_repository.get_by_id(
            permission_request.requester_id
        )
        reviewer = (
            await self.user_repository.get_by_id(permission_request.reviewed_by)
            if permission_request.reviewed_by is not None
            else None
        )
        revoker = (
            await self.user_repository.get_by_id(permission_request.revoked_by)
            if permission_request.revoked_by is not None
            else None
        )
        selected_approver = (
            await self.user_repository.get_by_id(permission_request.selected_approver_id)
            if permission_request.selected_approver_id is not None
            else None
        )

        return PermissionRequestResponse(
            request_id=permission_request.request_id,
            requester_id=permission_request.requester_id,
            requester_name=requester.name if requester is not None else None,
            permission_id=permission_request.permission_id,
            permission_name=permission_request.permission.permission_name,
            requested_role=permission_request.requested_role,
            selected_approver_id=permission_request.selected_approver_id,
            selected_approver_name=(
                selected_approver.name if selected_approver is not None else None
            ),
            reason=permission_request.reason,
            scope_ticket_id=permission_request.scope_ticket_id,
            status=permission_request.status,
            reviewed_by=permission_request.reviewed_by,
            reviewed_by_name=reviewer.name if reviewer is not None else None,
            reviewed_at=permission_request.reviewed_at,
            review_comment=permission_request.review_comment,
            expires_at=permission_request.expires_at,
            granted_override_id=permission_request.granted_override_id,
            revoked_at=permission_request.revoked_at,
            revoked_by=permission_request.revoked_by,
            revoked_by_name=revoker.name if revoker is not None else None,
            revoke_reason=permission_request.revoke_reason,
            can_revoke=(
                self._can_revoke(current_user, permission_request)
                if current_user is not None
                else False
            ),
            created_at=permission_request.created_at,
        )
