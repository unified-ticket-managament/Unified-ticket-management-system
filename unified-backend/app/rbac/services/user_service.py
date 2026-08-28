import json
from uuid import UUID

from fastapi import HTTPException, status

from shared_models.models import User

from app.auth.password import get_password_hash
from app.rbac.repositories import CategoryRepository, RoleRepository, UserRepository
from app.rbac.schemas.audit_log import AuditLogCreate
from app.rbac.schemas.user import UserCreate, UserUpdate
from app.rbac.services import access_control
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

# The five internal-organization roles (every role except Client) — see
# access_control.USER_CREATION_ROLE_MATRIX for who may assign them.
# Designation is mandatory for all five; Personal Email
# (users.alternate_email) likewise. Reporting Manager
# (users.reporting_manager_id) is mandatory for all five except Site
# Lead — see REPORTING_MANAGER_OPTIONAL_ROLE_NAMES below.
DESIGNATION_REQUIRED_ROLE_NAMES = {
    "Super Admin", "Site Lead", "Account Manager", "Team Lead", "Staff",
}
REPORTING_MANAGER_OPTIONAL_ROLE_NAMES = {"Site Lead"}

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

        # Backend-enforced mirror of the frontend's CREATABLE_ROLES_BY_ROLE
        # dropdown filter — a crafted request can't bypass it just because
        # the actor holds `user:create` in general. Checked before either
        # branch below, since it applies identically to Client and every
        # internal role.
        if actor is not None:
            access_control.ensure_can_create_role(actor, role.name)

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

        # Staff/Team Lead must belong to at least one work-
        # specialization category; every other role leaves it unset.
        # `category_ids` (new, multi-category-aware) and the legacy
        # singular `category_id` are merged into one list — see
        # _resolve_category_ids's own docstring for the conflict rule.
        category_ids = self._resolve_category_ids(user_data.category_id, user_data.category_ids)

        if role.name in CATEGORY_REQUIRED_ROLE_NAMES and not category_ids:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Category is required for Staff and Team Lead users.",
            )

        # Designation/Personal Email/Reporting Manager are mandatory for
        # every internal role except Reporting Manager on Site Lead — see
        # DESIGNATION_REQUIRED_ROLE_NAMES/REPORTING_MANAGER_OPTIONAL_ROLE_NAMES.
        if role.name in DESIGNATION_REQUIRED_ROLE_NAMES:
            if not user_data.designation or not user_data.designation.strip():
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Designation is required.",
                )
            if not user_data.alternate_email or not user_data.alternate_email.strip():
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Personal Email is required.",
                )
            if (
                role.name not in REPORTING_MANAGER_OPTIONAL_ROLE_NAMES
                and user_data.reporting_manager_id is None
            ):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Reporting Manager is required.",
                )
            if not user_data.employee_number or not user_data.employee_number.strip():
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Employee ID is required.",
                )
            if await self.user_repository.exists_by_employee_number(user_data.employee_number):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Employee ID already exists.",
                )

        if category_ids:
            found_categories = await self.category_repository.get_by_ids(category_ids)
            if len(found_categories) != len(set(category_ids)):
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="One or more categories were not found.",
                )

        # Validate manager/team-lead — see _validate_manager_and_teamlead's
        # own docstring for why existence alone (the old check here)
        # isn't enough to keep the Organization Structure's reporting
        # shape intact.
        await self._validate_manager_and_teamlead(
            role.name,
            user_data.manager_id,
            user_data.teamlead_id,
            category_ids,
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
            category_id=category_ids[0] if category_ids else None,
            is_active=user_data.is_active,
            # Required (validated above) for every internal role — see
            # DESIGNATION_REQUIRED_ROLE_NAMES. Previously never
            # persisted here at all (the old Create User form never
            # sent them), a latent gap that would have silently
            # dropped them now that they're mandatory.
            designation=user_data.designation,
            alternate_email=user_data.alternate_email,
            employee_number=user_data.employee_number,
        )

        user = await self.user_repository.create(user)

        if category_ids:
            user = await self.set_user_categories(user.user_id, category_ids, actor)
        else:
            user.category_ids = []

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

        `UserResponse.email` is a required `EmailStr` — but
        `Client.inbox_email` is nullable now (a client with no
        configured distribution email genuinely has none; see
        `Client`'s own docstring). Rather than let that surface as an
        opaque pydantic validation 500 the first time such a client is
        fetched/updated/(de)activated by id, this is a clear, explicit
        409 instead.
        """

        if client.inbox_email is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "This client has no configured distribution email, so it "
                    "can't be viewed or managed as a Client user yet — set "
                    "one first (via the Clients admin page, or this "
                    "endpoint's own email field)."
                ),
            )

        return {
            "user_id": client.client_id,
            "name": client.name,
            "email": client.inbox_email,
            "role_id": client_role_id,
            "manager_id": client.account_manager_id,
            "teamlead_id": None,
            "reporting_manager_id": None,
            "category_id": None,
            "category_ids": [],
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

    @staticmethod
    def _normalize_contact_emails(contact_emails: list[str] | None) -> list[str]:
        """
        At least one contact email is required for a Client (see root
        CLAUDE.md's Client-role section and the create-form spec this
        validates against); no fixed maximum. Rejects a case-insensitive
        duplicate within the same submitted list up front with a clear
        400 rather than letting it fall through to client_contacts'
        own (client_id, email) unique-constraint violation.
        """

        emails = [email.strip() for email in (contact_emails or []) if email and email.strip()]

        if not emails:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="At least one contact email is required.",
            )

        seen: set[str] = set()
        for email in emails:
            normalized = email.lower()
            if normalized in seen:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Duplicate contact email: {email}.",
                )
            seen.add(normalized)

        return emails

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

        contact_emails = self._normalize_contact_emails(user_data.contact_emails)

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

        # If contact persistence below raises, the just-created `clients`
        # row is rolled back too — no explicit commit happens anywhere in
        # this request until the surrounding get_db dependency's own
        # request-scoped session commits after a successful response, so
        # an exception here rolls back both writes together.
        await self.client_repository.set_contacts(client.client_id, contact_emails)

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

        unsupported_fields = update_data.keys() & {"category_id", "category_ids", "teamlead_id"}
        if unsupported_fields:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Client users do not support: {', '.join(sorted(unsupported_fields))}.",
            )

        # Full-replace semantics — see ClientRepository.set_contacts'
        # own docstring. Popped out of update_data (rather than left
        # in) since it has no column on `clients` itself for the
        # update_linked_fields call below.
        new_contact_emails = update_data.pop("contact_emails", None)

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

            existing_category = await self.category_repository.get_active_by_inbox_email(
                update_data["email"]
            )
            if existing_category is not None:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="This address is already configured as a category mailbox.",
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

        if new_contact_emails is not None:
            await self.client_repository.set_contacts(
                client.client_id, self._normalize_contact_emails(new_contact_emails)
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

    @staticmethod
    def _resolve_category_ids(
        category_id: UUID | None,
        category_ids: list[UUID] | None,
    ) -> list[UUID]:
        """
        Normalizes the legacy singular `category_id` and the new
        plural `category_ids` into one list. Both may be sent
        together (e.g. an older client still populating category_id
        alongside a newer one sending category_ids) as long as they
        agree that `category_id == category_ids[0]` — a genuine
        conflict (category_id=X but category_ids=[Y, Z]) is rejected
        with a clear 400 rather than silently preferring one.
        """

        ids = list(category_ids) if category_ids else []

        if category_id is not None:
            if ids:
                if ids[0] != category_id:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="category_id must match the first entry of category_ids.",
                    )
            else:
                ids = [category_id]

        return ids

    async def set_user_categories(
        self,
        user_id: UUID,
        category_ids: list[UUID],
        actor: User | None = None,
    ) -> User:
        """
        Full-replace a user's category-membership set (the
        many-to-many `user_categories` join table), keeping
        `users.category_id` in sync as a "legacy primary category" —
        the first id in `category_ids`, or None if the list is empty.
        There's no separate "mark as primary" UI; whichever category
        the caller submits first simply wins.

        Unconditionally bumps `permission_version`, even when the
        scalar `category_id` happens to stay the same (e.g. adding a
        2nd category without changing the first) — update_user's own
        `_RBAC_RELEVANT_FIELDS` diff-based bump would otherwise miss
        exactly that case, since it only compares the scalar field.
        Same pattern as activate_user/deactivate_user's own
        unconditional bumps.
        """

        user = await self.user_repository.get_by_id(user_id)
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found.",
            )

        if category_ids:
            found_categories = await self.category_repository.get_by_ids(category_ids)
            if len(found_categories) != len(set(category_ids)):
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="One or more categories were not found.",
                )

        await self.user_repository.replace_categories(
            user_id,
            category_ids,
            assigned_by=actor.user_id if actor else None,
        )

        user.category_id = category_ids[0] if category_ids else None
        user.permission_version += 1

        user = await self.user_repository.update(user)
        # Known-correct list already in hand — set directly rather
        # than re-reading `.categories` after update()'s own refresh(),
        # which may or may not still have it loaded.
        user.category_ids = category_ids
        return user

    async def _validate_manager_and_teamlead(
        self,
        role_name: str,
        manager_id: UUID | None,
        teamlead_id: UUID | None,
        category_ids: list[UUID] | None,
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
            # a Team Lead may now own several business categories — so
            # every category assigned to the Staff member must be
            # among the Team Lead's own categories (a subset check, not
            # exact-set equality: a Team Lead can legitimately cover
            # more categories than one Staff member needs, e.g. a
            # multi-category Team Lead like Yashodha covering both
            # Payment Posting and Quality can still take on Staff who
            # only work one of the two). A Team Lead with no category
            # assigned yet (shouldn't normally happen — category is
            # required for that role — but could exist on old data)
            # doesn't block this, since there's nothing to mismatch
            # against.
            teamlead_category_ids = {c.category_id for c in teamlead.categories}
            if (
                category_ids
                and teamlead_category_ids
                and not set(category_ids).issubset(teamlead_category_ids)
            ):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="The assigned Team Lead's categories must include this user's own categories.",
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

    @staticmethod
    def _attach_category_ids_from_loaded(user: User) -> User:
        """
        Sets the transient, non-persisted `category_ids` attribute
        that `UserResponse.category_ids` reads via `from_attributes`
        (the ORM relationship is named `categories`, a list of
        `Category` objects — a different name/shape, so it never
        auto-populates the response field on its own). Same "bolt a
        transient attribute onto the User instance" pattern already
        used for `.permissions`/`.scoped_permissions` elsewhere in
        this codebase.

        Only call this where `.categories` is known to already be
        eager-loaded (selectinload) on `user` — never on a path where
        it might still be an unloaded relationship, which would
        trigger a synchronous lazy-load and crash with MissingGreenlet
        in this async context.
        """

        user.category_ids = [c.category_id for c in user.categories]
        return user

    async def get_user(
        self,
        user_id: UUID,
    ):

        user, client = await self._resolve_user_or_client(user_id)

        if user is not None:
            return self._attach_category_ids_from_loaded(user)

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
        category_ids: list[UUID] | None = None,
        current_user: User | None = None,
        include_reporting_scope: bool = False,
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

        `include_reporting_scope`, when True, widens the Account
        Manager/Team Lead/Staff branches above with
        OrganizationService.get_reporting_scope_user_ids instead of
        the narrower baseline — used only by the Users-management
        page's own request (`GET /users?include_reporting_scope=true`).
        Defaults to False so every other existing caller of this
        method (Audit Logs, the User Detail Drawer, the Roles page,
        the Reporting Managers admin page, the dashboard user list) is
        completely unaffected.
        """

        visible_user_ids: set[UUID] | None = None

        if current_user is None:
            visible_user_ids = set()
        elif include_reporting_scope:
            visible_user_ids = await self.organization_service.get_reporting_scope_user_ids(
                current_user
            )
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
            category_ids,
            visible_user_ids,
        )

        reporting_manager_ids = await self.organization_service.get_reporting_manager_user_ids(
            [user.user_id for user in users]
        )

        for user in users:
            self._attach_category_ids_from_loaded(user)
            user.is_reporting_manager = user.user_id in reporting_manager_ids

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

        # `category_ids` has no ORM column of its own (it's a
        # many-to-many collection, not a scalar field) — pulled out
        # up front so the generic setattr/old_values/audit-log loops
        # below never touch it directly. Applied at the very end via
        # set_user_categories instead, which also keeps the legacy
        # scalar `category_id` column in sync.
        category_ids_update = update_data.pop("category_ids", None)

        # Snapshotted now, while `.categories` is known-loaded (from
        # _resolve_user_or_client's get_by_id) — used as the response's
        # `category_ids` if this update doesn't touch categories at
        # all, so nothing later needs to re-read the relationship after
        # user_repository.update()'s own flush/refresh.
        existing_category_ids_snapshot = [c.category_id for c in user.categories]

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

            # Same backend-enforced role-vs-role check create_user runs —
            # changing a user's role via Edit User is just as much a
            # "create/assign this role" action as the initial creation.
            if actor is not None:
                access_control.ensure_can_create_role(actor, new_role.name)

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
        category_fields_touched = (
            category_ids_update is not None or "category_id" in update_data
        )

        if category_fields_touched or update_data.keys() & {
            "role_id", "manager_id", "teamlead_id",
        }:
            effective_manager_id = update_data.get("manager_id", user.manager_id)
            effective_teamlead_id = update_data.get("teamlead_id", user.teamlead_id)

            if category_fields_touched:
                effective_category_ids = self._resolve_category_ids(
                    update_data.get("category_id"), category_ids_update,
                )
            else:
                effective_category_ids = [c.category_id for c in user.categories] or (
                    [user.category_id] if user.category_id else []
                )

            await self._validate_manager_and_teamlead(
                final_role_name,
                effective_manager_id,
                effective_teamlead_id,
                effective_category_ids,
            )

        # Designation/Personal Email/Reporting Manager required-ness —
        # re-checked whenever role_id changes (a new role may have
        # different requirements) or one of the fields being checked is
        # itself being cleared, falling back to the user's existing
        # value otherwise (mirrors the manager/teamlead check above).
        if update_data.keys() & {"role_id", "designation", "alternate_email", "reporting_manager_id"}:
            if final_role_name in DESIGNATION_REQUIRED_ROLE_NAMES:
                effective_designation = update_data.get("designation", user.designation)
                effective_alternate_email = update_data.get("alternate_email", user.alternate_email)
                effective_reporting_manager_id = update_data.get(
                    "reporting_manager_id", user.reporting_manager_id
                )

                if not effective_designation or not str(effective_designation).strip():
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Designation is required.",
                    )
                if not effective_alternate_email or not str(effective_alternate_email).strip():
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Personal Email is required.",
                    )
                if (
                    final_role_name not in REPORTING_MANAGER_OPTIONAL_ROLE_NAMES
                    and effective_reporting_manager_id is None
                ):
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Reporting Manager is required.",
                    )

        # reporting_manager_id is deliberately NOT in the manager_id/
        # teamlead_id trigger set two blocks up — it's an Organization-
        # Chart-only field with no RBAC/authorization meaning (see
        # OrganizationService's docstring), so editing it alone must not
        # bump permission_version or re-run the unrelated manager_id/
        # teamlead_id reporting-line check (it's still covered by the
        # designation/reporting-manager required-ness block immediately
        # above, and by its own existence check right here).
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

        # Keep the many-to-many `user_categories` join table in sync
        # with whatever category information was actually submitted —
        # the new plural `category_ids` if present, else the legacy
        # singular `category_id` alone (so an old caller that only
        # ever sends `category_id` still keeps the join table
        # consistent). Neither present means categories weren't
        # touched by this update at all.
        if category_ids_update is not None:
            user = await self.set_user_categories(user.user_id, category_ids_update, actor)
        elif "category_id" in update_data:
            legacy_category_id = update_data["category_id"]
            user = await self.set_user_categories(
                user.user_id,
                [legacy_category_id] if legacy_category_id is not None else [],
                actor,
            )
        else:
            user.category_ids = existing_category_ids_snapshot

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

        # Snapshotted before activate()'s own flush/refresh — read
        # while `.categories` is known-loaded (from _resolve_user_or_
        # client's get_by_id), rather than re-reading the relationship
        # afterward and risking an async lazy-load if refresh() has
        # expired it.
        category_ids_snapshot = [c.category_id for c in user.categories]

        user.permission_version += 1

        user = await self.user_repository.activate(
            user
        )
        user.category_ids = category_ids_snapshot

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

        category_ids_snapshot = [c.category_id for c in user.categories]

        user.permission_version += 1

        user = await self.user_repository.deactivate(
            user
        )
        user.category_ids = category_ids_snapshot

        await self.audit_log_service.create_log(
            AuditLogCreate(
                user_id=actor.user_id if actor else None,
                action="user.deactivate",
                entity_type="user",
                entity_id=str(user.user_id),
            )
        )

    # --------------------------------------------------
    # Admin password reset (RBAC Enforcement Audit, Phase 23) — distinct
    # from AuthService.change_password's self-service flow. Gated by
    # user:reset_password on the caller's own route (see users.py), not
    # here — checked by the route, not the service. No old_password is
    # required or accepted, since the actor is not the account owner.
    # Reuses the same hashing utility and User.password_hash column
    # self-service change_password already uses — no second hashing
    # mechanism. Deliberately does not bump permission_version or
    # otherwise touch session/JWT state, mirroring change_password's
    # own behavior exactly: password is not a JWT claim, and this
    # codebase's stateless-JWT architecture has no session table to
    # invalidate either way (see AuthService.logout's own docstring).

    async def reset_password(
        self,
        user_id: UUID,
        new_password: str,
        actor: User | None = None,
    ) -> None:

        user, client = await self._resolve_user_or_client(user_id)

        if client is not None:
            # A Client has no login of its own (see root CLAUDE.md's
            # Client-role section) — nothing to reset.
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="This account has no password to reset.",
            )

        user.password_hash = get_password_hash(new_password)

        await self.user_repository.update(user)

        await self.audit_log_service.create_log(
            AuditLogCreate(
                user_id=actor.user_id if actor else None,
                action="user.reset_password",
                entity_type="user",
                entity_id=str(user.user_id),
            )
        )

        return user