import json
from uuid import UUID

from fastapi import HTTPException, status

from shared_models.models import User

from app.auth.password import get_password_hash
from app.rbac.repositories import CategoryRepository, RoleRepository, UserRepository
from app.rbac.schemas.audit_log import AuditLogCreate
from app.rbac.schemas.user import UserCreate, UserUpdate
from app.rbac.services.audit_log_service import AuditLogService
from app.rbac.services.organization_service import OrganizationService
from app.ticketing.models.client import Client
from app.ticketing.repositories.client_repository import ClientRepository
from app.ticketing.schemas.client import ClientCreate
from app.ticketing.services.client_service import ClientService

# Roles required to belong to a work-specialization category — see
# shared_models.models.Category. Not imported from a shared constant
# because RBAC's role-name literals live only in the frontend's
# role-access.ts today; keep this set in sync with it by hand.
CATEGORY_REQUIRED_ROLE_NAMES = {"Staff", "Team Lead"}

# The client-facing role (renamed from "Viewer" — see root CLAUDE.md's
# Client-role section). Unlike every other role, a "Client" user is
# never stored in `users` at all — see the "Client storage" block of
# methods below. It has no reporting-hierarchy/category concept of its
# own and no password, so it's handled as a fully separate branch
# through create/get/list/update/delete/activate/deactivate rather
# than folded into the internal-user code path.
CLIENT_ROLE_NAME = "Client"

# Fields whose change should invalidate any already-issued session's
# cached RBAC state (see User.permission_version's own docstring and
# app/core/rbac_cache.py) — role/category/reporting-line reassignment
# all change what a user is authorized to do or see. `name`/`email`
# are deliberately excluded: cosmetic, not authorization-relevant, and
# already accepted as "stale until next token refresh" the same way
# permissions/scoped_permissions are.
_RBAC_RELEVANT_FIELDS = {"role_id", "category_id", "manager_id", "teamlead_id"}


class UserService:
    """
    Business logic for User operations.
    """

    def __init__(
        self,
        user_repository: UserRepository,
        role_repository: RoleRepository,
        category_repository: CategoryRepository,
        audit_log_service: AuditLogService,
        client_repository: ClientRepository,
        client_service: ClientService,
        organization_service: OrganizationService,
    ):
        self.user_repository = user_repository
        self.role_repository = role_repository
        self.category_repository = category_repository
        self.audit_log_service = audit_log_service
        self.client_repository = client_repository
        self.client_service = client_service
        self.organization_service = organization_service

    # --------------------------------------------------
    # Create User
    # --------------------------------------------------

    async def create_user(
            self,
            user_data: UserCreate,
            actor: User | None = None,
        ):

        # Check role exists
        role = await self.role_repository.get_by_id(
            user_data.role_id
        )

        if role is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Role not found.",
            )

        # A "Client" user is never stored in `users` at all — see
        # CLIENT_ROLE_NAME's own docstring and root CLAUDE.md's
        # Client-role section. Fully separate branch, own storage.
        if role.name == CLIENT_ROLE_NAME:
            return await self._create_client_user(user_data, role, actor)

        # Check email already exists
        if await self.user_repository.exists(user_data.email):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email already exists.",
            )

        # Staff/Team Lead must belong to a work-specialization
        # category; every other role leaves it unset.
        if role.name in CATEGORY_REQUIRED_ROLE_NAMES and user_data.category_id is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Category is required for Staff and Team Lead users.",
            )

        if user_data.category_id is not None:

            category = await self.category_repository.get_by_id(
                user_data.category_id
            )

            if category is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Category not found.",
                )

        # Validate manager/team-lead — see _validate_manager_and_teamlead's
        # own docstring for why existence alone (the old check here)
        # isn't enough to keep the Organization Structure's reporting
        # shape intact.
        await self._validate_manager_and_teamlead(
            role.name,
            user_data.manager_id,
            user_data.teamlead_id,
            user_data.category_id,
        )
        await self._validate_reporting_manager_id(user_data.reporting_manager_id)

        user = User(
            name=user_data.name,
            email=user_data.email,
            password_hash=get_password_hash(
                user_data.password
            ),
            role_id=user_data.role_id,
            manager_id=user_data.manager_id,
            teamlead_id=user_data.teamlead_id,
            reporting_manager_id=user_data.reporting_manager_id,
            category_id=user_data.category_id,
            is_active=user_data.is_active,
        )

        user = await self.user_repository.create(user)

        await self.audit_log_service.create_log(
            AuditLogCreate(
                user_id=actor.user_id if actor else None,
                action="user.create",
                entity_type="user",
                entity_id=str(user.user_id),
                new_value=json.dumps(
                    {"name": user.name, "email": user.email, "role_id": str(user.role_id)}
                ),
            )
        )

        return user

    # --------------------------------------------------
    # Client storage — a "Client" user lives only in `clients`,
    # never in `users` (see root CLAUDE.md's Client-role section)
    # --------------------------------------------------

    async def _resolve_client_role_id(self) -> UUID:
        role = await self.role_repository.get_by_name(CLIENT_ROLE_NAME)

        if role is None:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="The Client role is not configured.",
            )

        return role.role_id

    def _client_to_user_response(self, client: Client, client_role_id: UUID) -> dict:
        """
        Shapes a `clients` row into the same dict shape UserResponse
        expects, so the Users page's list/get/create/update/filter/
        search all keep working unchanged against a merged view of
        real internal users and Client "virtual users" — see root
        CLAUDE.md's Client-role section. `client_id` doubles as
        `user_id` here; a Client has no category/teamlead/profile
        fields of its own, so those are always null.
        """

        return {
            "user_id": client.client_id,
            "name": client.name,
            "email": client.inbox_email,
            "role_id": client_role_id,
            "manager_id": client.account_manager_id,
            "teamlead_id": None,
            "reporting_manager_id": None,
            "category_id": None,
            "is_active": client.is_active,
            "date_of_birth": None,
            "alternate_email": None,
            "phone_number": None,
            "office_location": None,
            "department": None,
            "team": None,
            "language": None,
            "date_format": None,
            "time_format": None,
            "time_zone": None,
            "default_dashboard": None,
            "created_at": client.created_at,
            "updated_at": client.updated_at,
        }

    async def _create_client_user(
        self,
        user_data: UserCreate,
        role,
        actor: User | None,
    ) -> dict:
        """
        Creates a Client user straight in the ticketing domain's
        `clients` table, via the same ClientService.create the
        standalone company-onboarding endpoint already uses (its own
        duplicate-inbox-email and active-Account-Manager checks apply
        unchanged here) — no `users` row is ever created for this
        role. `user_data.password` is accepted but intentionally
        unused: a Client has no login of its own.
        """

        if user_data.manager_id is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="An Account Manager must be assigned when creating a Client user.",
            )

        if await self.user_repository.exists(user_data.email):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email already exists.",
            )

        created = await self.client_service.create(
            ClientCreate(
                name=user_data.name,
                inbox_email=user_data.email,
                account_manager_id=user_data.manager_id,
            ),
            current_user=actor,
        )

        client = await self.client_repository.get_by_id(created.client_id)

        if not user_data.is_active:
            client = await self.client_repository.update_linked_fields(
                client, is_active=False
            )

        await self.audit_log_service.create_log(
            AuditLogCreate(
                user_id=actor.user_id if actor else None,
                action="user.create",
                entity_type="client",
                entity_id=str(client.client_id),
                new_value=json.dumps(
                    {"name": client.name, "email": client.inbox_email, "role": CLIENT_ROLE_NAME}
                ),
            )
        )

        return self._client_to_user_response(client, role.role_id)

    async def _update_client_user(
        self,
        client: Client,
        user_data: UserUpdate,
        actor: User | None,
    ) -> dict:
        """
        Edits an existing Client "virtual user" (see create_user's
        Client branch above). A Client has no role/category/teamlead
        concept — only name, email, its owning Account Manager
        (manager_id), and is_active are meaningful here.
        """

        update_data = user_data.model_dump(exclude_unset=True)

        # The edit form always resubmits role_id unchanged alongside
        # whatever the user actually edited — only reject it if it's a
        # genuine attempt to change role, not just a no-op resend. It
        # has no bearing on a Client row either way, so drop it once
        # validated rather than trying to "apply" it.
        if "role_id" in update_data:
            client_role_id = await self._resolve_client_role_id()
            if str(update_data.pop("role_id")) != str(client_role_id):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Cannot change an existing Client user's role. Create a new user instead.",
                )

        unsupported_fields = update_data.keys() & {"category_id", "teamlead_id"}
        if unsupported_fields:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Client users do not support: {', '.join(sorted(unsupported_fields))}.",
            )

        if "email" in update_data:
            existing_client = await self.client_repository.get_by_inbox_email(
                update_data["email"]
            )
            if existing_client is not None and existing_client.client_id != client.client_id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Email already exists.",
                )

            if await self.user_repository.exists(update_data["email"]):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Email already exists.",
                )

        effective_manager_id = update_data.get("manager_id", client.account_manager_id)
        if effective_manager_id is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="An Account Manager must be assigned to a Client user.",
            )

        if "manager_id" in update_data:
            await self._validate_manager_and_teamlead(
                CLIENT_ROLE_NAME, effective_manager_id, None, None,
            )

        old_values = {
            "name": client.name,
            "email": client.inbox_email,
            "manager_id": str(client.account_manager_id),
            "is_active": client.is_active,
        }

        client = await self.client_repository.update_linked_fields(
            client,
            name=update_data.get("name"),
            inbox_email=update_data.get("email"),
            account_manager_id=update_data.get("manager_id"),
            is_active=update_data.get("is_active"),
        )

        if update_data:
            await self.audit_log_service.create_log(
                AuditLogCreate(
                    user_id=actor.user_id if actor else None,
                    action="user.update",
                    entity_type="client",
                    entity_id=str(client.client_id),
                    old_value=json.dumps(old_values),
                    new_value=json.dumps(
                        {k: (str(v) if v is not None else None) for k, v in update_data.items()}
                    ),
                )
            )

        return self._client_to_user_response(client, await self._resolve_client_role_id())

    # --------------------------------------------------
    # Reporting-line validation
    # --------------------------------------------------

    async def _validate_manager_and_teamlead(
        self,
        role_name: str,
        manager_id: UUID | None,
        teamlead_id: UUID | None,
        category_id: UUID | None,
    ) -> None:
        """
        Enforces the Organization Structure's reporting shape (see root
        CLAUDE.md): Super Admin > Site Lead > Account Manager > Team
        Lead > Staff. manager_id/teamlead_id previously only checked
        that the referenced user existed at all — nothing stopped a
        Staff member's teamlead_id from pointing at another Staff
        member, or a Team Lead's manager_id from pointing at a
        different Team Lead.
        """

        if manager_id is not None:
            manager = await self.user_repository.get_by_id(manager_id)

            if manager is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Manager not found.",
                )

            # An Account Manager's own manager (if ever set — it's
            # usually left null, falling back to the first Super Admin,
            # see OrganizationService._get_parent) sits one level up at
            # Site Lead/Super Admin; every other role's manager_id is
            # the Account Manager one level up from it.
            expected_roles = (
                {"Site Lead", "Super Admin"}
                if role_name == "Account Manager"
                else {"Account Manager"}
            )

            if manager.role.name not in expected_roles:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=(
                        "manager_id must reference a user holding one of "
                        f"these roles: {', '.join(sorted(expected_roles))}."
                    ),
                )

        if teamlead_id is not None:
            teamlead = await self.user_repository.get_by_id(teamlead_id)

            if teamlead is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Team Lead not found.",
                )

            if teamlead.role.name != "Team Lead":
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="teamlead_id must reference a user holding the Team Lead role.",
                )

            # Every Staff member belongs to exactly one Team Lead, and
            # a Team Lead owns exactly one business category — so the
            # Staff member's own category must match theirs. A Team
            # Lead with no category assigned yet (shouldn't normally
            # happen — category is required for that role — but could
            # exist on old data) doesn't block this, since there's
            # nothing to mismatch against.
            if (
                category_id is not None
                and teamlead.category_id is not None
                and teamlead.category_id != category_id
            ):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="The assigned Team Lead's category must match this user's own category.",
                )

    async def _validate_reporting_manager_id(
        self,
        reporting_manager_id: UUID | None,
        self_id: UUID | None = None,
    ) -> None:
        """
        Lightweight validation for the Organization-Chart-only
        reporting_manager_id field — deliberately unrestricted by role
        (unlike manager_id/teamlead_id's _validate_manager_and_teamlead
        above), since the chart must reflect the real reporting line
        exactly as the database says, not one inferred from role names.
        Only checks that the target exists and isn't the user's own id;
        full cycle protection (A -> B -> A) is handled defensively by
        OrganizationService's own chart-building guards, not enforced
        at write time.
        """

        if reporting_manager_id is None:
            return

        if self_id is not None and reporting_manager_id == self_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="A user cannot be their own reporting manager.",
            )

        target = await self.user_repository.get_by_id(reporting_manager_id)

        if target is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Reporting manager not found.",
            )

    # --------------------------------------------------
    # Get User
    # --------------------------------------------------

    async def _resolve_user_or_client(self, user_id: UUID) -> tuple[User | None, Client | None]:
        """
        Looks `user_id` up against both possible storage tables — a
        real `users` row for every internal role, or a `clients` row
        for a "Client" user (see root CLAUDE.md's Client-role
        section). Raises 404 if it matches neither.
        """

        user = await self.user_repository.get_by_id(user_id)
        if user is not None:
            return user, None

        client = await self.client_repository.get_by_id(user_id)
        if client is not None:
            return None, client

        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found.",
        )

    async def get_user(
        self,
        user_id: UUID,
    ):

        user, client = await self._resolve_user_or_client(user_id)

        if user is not None:
            return user

        return self._client_to_user_response(client, await self._resolve_client_role_id())

    async def get_user_by_email(
        self,
        email: str,
    ) -> User:

        user = await self.user_repository.get_by_email(
            email
        )

        if user is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found.",
            )

        return user

    async def list_users(
        self,
        page: int = 1,
        page_size: int = 10,
        search: str | None = None,
        category_id: UUID | None = None,
        current_user: User | None = None,
    ):
        """
        Returns the Users-management listing — real application users
        only. `Client` company records (app.ticketing.Client, e.g.
        "APM") are deliberately never included here: they aren't
        users, have no reporting-hierarchy/category concept, and
        showing them in this list conflated two entities that only
        happen to share a "Client" role label. This used to merge in
        a synthesized pseudo-User row per Client company (see
        _client_to_user_response's own docstring) — removed, since
        that's exactly the reported bug this method now fixes. The
        per-id Client-as-pseudo-user machinery elsewhere in this class
        (_resolve_user_or_client, used by get/update/deactivate-by-id)
        is untouched — only this listing no longer surfaces them.

        Also enforces the caller's own reporting-hierarchy visibility
        scope server-side (previously only done, insecurely, via
        client-side filtering in the Users page) — reusing
        OrganizationService.get_subordinate_user_ids, the same
        real manager_id/teamlead_id traversal already trusted to scope
        permission-override grant authority, rather than inventing a
        second hierarchy model:
          - Super Admin / Site Lead: unrestricted (every real user).
          - Account Manager / Team Lead: their own reporting subtree
            only (recursive — an Account Manager's scope includes
            their Team Leads' own Staff, not just direct reports).
          - Staff (or any other role): themselves only.
        `current_user=None` (no authenticated caller resolved) is
        treated as the safest default — see-nothing — rather than
        unrestricted; every real caller of this method always has one.
        """

        visible_user_ids: set[UUID] | None = None

        if current_user is None:
            visible_user_ids = set()
        else:
            role_name = current_user.role.name if current_user.role is not None else None

            if role_name in ("Super Admin", "Site Lead"):
                visible_user_ids = None
            elif role_name in ("Account Manager", "Team Lead"):
                visible_user_ids = await self.organization_service.get_subordinate_user_ids(
                    current_user
                )
            else:
                visible_user_ids = {current_user.user_id}

        users, total = await self.user_repository.get_all(
            page,
            page_size,
            search,
            category_id,
            visible_user_ids,
        )

        return users, total

    # --------------------------------------------------
    # Update User
    # --------------------------------------------------

    async def update_user(
        self,
        user_id: UUID,
        user_data: UserUpdate,
        actor: User | None = None,
    ):

        user, client = await self._resolve_user_or_client(user_id)

        if client is not None:
            return await self._update_client_user(client, user_data, actor)

        update_data = user_data.model_dump(
            exclude_unset=True
        )

        # Email validation
        if "email" in update_data:

            existing = await self.user_repository.get_by_email(
                update_data["email"]
            )

            if (
                existing
                and existing.user_id != user.user_id
            ):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Email already exists.",
                )

        # Role validation
        new_role = None
        if "role_id" in update_data:

            new_role = await self.role_repository.get_by_id(
                update_data["role_id"]
            )

            if new_role is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Role not found.",
                )

            # An internal user's storage table is decided once, at
            # create time, by which role was picked (see
            # CLIENT_ROLE_NAME's own docstring) — a Client lives at a
            # different primary key (client_id) entirely, so "becoming"
            # one isn't an in-place role change this endpoint supports.
            if new_role.name == CLIENT_ROLE_NAME:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=(
                        "Cannot change an existing user's role to Client. "
                        "Create a new Client user instead."
                    ),
                )

        # Used below by the reporting-line validation — the role this
        # user will hold *after* this update is saved, whether or not
        # role_id itself changed.
        final_role_name = new_role.name if new_role is not None else user.role.name

        # Reporting-line validation — re-runs whenever any field that
        # affects the check's own inputs is touched (not just when
        # manager_id/teamlead_id themselves change), e.g. changing
        # category_id alone must still be checked against an existing
        # teamlead_id. Falls back to the user's current value for
        # anything not present in this particular update.
        if update_data.keys() & {"role_id", "category_id", "manager_id", "teamlead_id"}:
            effective_manager_id = update_data.get("manager_id", user.manager_id)
            effective_teamlead_id = update_data.get("teamlead_id", user.teamlead_id)
            effective_category_id = update_data.get("category_id", user.category_id)

            await self._validate_manager_and_teamlead(
                final_role_name,
                effective_manager_id,
                effective_teamlead_id,
                effective_category_id,
            )

        # reporting_manager_id is deliberately NOT in the trigger set
        # above — it's an Organization-Chart-only field with no RBAC/
        # authorization meaning (see OrganizationService's docstring),
        # so editing it alone must not bump permission_version or
        # re-run the unrelated manager_id/teamlead_id reporting-line
        # check.
        if "reporting_manager_id" in update_data:
            await self._validate_reporting_manager_id(
                update_data["reporting_manager_id"], self_id=user.user_id
            )

        old_values = {
            field: (str(getattr(user, field)) if getattr(user, field) is not None else None)
            for field in update_data
        }
        old_role_id = user.role_id
        old_is_active = user.is_active

        for field, value in update_data.items():
            setattr(user, field, value)

        # Any of these change what this user is authorized to do or
        # see — bump so a session already in flight with the old
        # value baked into its JWT gets rejected on its next DB-
        # verified request instead of trusting a stale role/category
        # for the rest of the token's natural TTL. See
        # app/core/rbac_cache.py's module docstring.
        if _RBAC_RELEVANT_FIELDS.intersection(update_data.keys()):
            user.permission_version += 1

        user = await self.user_repository.update(user)

        if update_data:
            await self.audit_log_service.create_log(
                AuditLogCreate(
                    user_id=actor.user_id if actor else None,
                    action="user.update",
                    entity_type="user",
                    entity_id=str(user.user_id),
                    old_value=json.dumps(old_values),
                    new_value=json.dumps(
                        {k: (str(v) if v is not None else None) for k, v in update_data.items()}
                    ),
                )
            )

        # "Role Changed" is logged as its own distinct action in
        # addition to the generic user.update row above — same
        # mutation, but callers that only care about role history
        # (not every profile-field edit) can filter on this action
        # name instead of parsing old_value/new_value.
        if "role_id" in update_data and str(old_role_id) != str(update_data["role_id"]):
            await self.audit_log_service.create_log(
                AuditLogCreate(
                    user_id=actor.user_id if actor else None,
                    action="user.role_changed",
                    entity_type="user",
                    entity_id=str(user.user_id),
                    old_value=json.dumps({"role_id": str(old_role_id)}),
                    new_value=json.dumps({"role_id": str(update_data["role_id"])}),
                )
            )

        # Same reasoning as role_changed above — is_active can also be
        # toggled through this generic update path (not only the
        # dedicated activate/deactivate endpoints below), so it gets
        # its own named action here too.
        if "is_active" in update_data and bool(old_is_active) != bool(update_data["is_active"]):
            await self.audit_log_service.create_log(
                AuditLogCreate(
                    user_id=actor.user_id if actor else None,
                    action="user.activate" if update_data["is_active"] else "user.deactivate",
                    entity_type="user",
                    entity_id=str(user.user_id),
                )
            )

        return user

    # --------------------------------------------------
    # Delete User
    # --------------------------------------------------

    async def delete_user(
        self,
        user_id: UUID,
        actor: User | None = None,
    ):

        user, client = await self._resolve_user_or_client(user_id)

        if client is not None:
            # Clients have no hard-delete endpoint anywhere in this
            # codebase (see ClientRepository) and ticket/interaction
            # history may still reference this client_id — deactivate
            # rather than risk an FK violation or orphaned history.
            client = await self.client_repository.update_linked_fields(
                client, is_active=False
            )

            await self.audit_log_service.create_log(
                AuditLogCreate(
                    user_id=actor.user_id if actor else None,
                    action="user.delete",
                    entity_type="client",
                    entity_id=str(client.client_id),
                    old_value=json.dumps({"name": client.name, "email": client.inbox_email}),
                )
            )
            return

        await self.user_repository.delete(user)

        await self.audit_log_service.create_log(
            AuditLogCreate(
                user_id=actor.user_id if actor else None,
                action="user.delete",
                entity_type="user",
                entity_id=str(user_id),
                old_value=json.dumps({"name": user.name, "email": user.email}),
            )
        )

    # --------------------------------------------------
    # Activate
    # --------------------------------------------------

    async def activate_user(
        self,
        user_id: UUID,
        actor: User | None = None,
    ):

        user, client = await self._resolve_user_or_client(user_id)

        if client is not None:
            client = await self.client_repository.update_linked_fields(
                client, is_active=True
            )

            await self.audit_log_service.create_log(
                AuditLogCreate(
                    user_id=actor.user_id if actor else None,
                    action="user.activate",
                    entity_type="client",
                    entity_id=str(client.client_id),
                )
            )

            return self._client_to_user_response(
                client, await self._resolve_client_role_id()
            )

        user.permission_version += 1

        user = await self.user_repository.activate(
            user
        )

        await self.audit_log_service.create_log(
            AuditLogCreate(
                user_id=actor.user_id if actor else None,
                action="user.activate",
                entity_type="user",
                entity_id=str(user.user_id),
            )
        )

        return user

    # --------------------------------------------------
    # Deactivate
    # --------------------------------------------------

    async def deactivate_user(
        self,
        user_id: UUID,
        actor: User | None = None,
    ):

        user, client = await self._resolve_user_or_client(user_id)

        if client is not None:
            client = await self.client_repository.update_linked_fields(
                client, is_active=False
            )

            await self.audit_log_service.create_log(
                AuditLogCreate(
                    user_id=actor.user_id if actor else None,
                    action="user.deactivate",
                    entity_type="client",
                    entity_id=str(client.client_id),
                )
            )

            return self._client_to_user_response(
                client, await self._resolve_client_role_id()
            )

        user.permission_version += 1

        user = await self.user_repository.deactivate(
            user
        )

        await self.audit_log_service.create_log(
            AuditLogCreate(
                user_id=actor.user_id if actor else None,
                action="user.deactivate",
                entity_type="user",
                entity_id=str(user.user_id),
            )
        )

        return user