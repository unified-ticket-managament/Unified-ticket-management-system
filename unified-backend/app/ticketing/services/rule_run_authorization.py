"""
Mail scope for "Run rule now" — who may a retroactive run act on.

Rule execution is not mail authorization. The live intake engine runs
every enabled rule against every inbound email regardless of who owns
the rule; Run rule now deliberately does NOT inherit that. Every
historical email must independently pass, for BOTH the rule's owner and
the user who triggered the run, the exact same per-interaction gate the
equivalent manual action uses:

- move_to_folder -> InteractionService.set_interaction_folder's gate
  (ensure_agent_can_view_pending_interaction with
  permission_backed="communication:move_to_folder",
  requires_delegated_access=True) plus that permission itself.
- forward_to -> InteractionService.forward_to_internal_user's gate
  (ticketed: ensure_agent_can_view_ticket +
  ensure_account_manager_owns_ticket_client; pending: the pending gate
  with "communication:reply_external") plus that permission itself.

The one deliberate difference from the manual actions: the delegated-
access retry (forward recipient / folder share — see
resolve_delegated_thread_access) is never attempted. A rule cannot
authorize itself: a folder the rule (or any rule) files mail into, or a
forward a rule sent, must never become the reason the same rule may act
on more mail. Only ownership-level access (or a global-inbox role)
counts.

Authorization is checked against the thread root (the same thread-
scoped model list views and delegated_access already use), using the
root's stored client_id/category_id/ticket_id — never re-resolved from
the sender.

Kept free of any run-now specifics beyond `RunScopeGate` so the live
engine can later adopt the same boundary.
"""

import logging
from typing import Iterable
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import and_, false, or_, select
from sqlalchemy.orm import aliased
from shared_models.models import User

from app.rbac.repositories.permission_override_repository import PermissionOverrideRepository
from app.rbac.repositories.reporting_manager_repository import ReportingManagerRepository
from app.rbac.repositories.role_permission_repository import RolePermissionRepository
from app.rbac.services.permission_resolver import PermissionResolverService
from app.ticketing.enums.rule_enums import RuleActionType
from app.ticketing.models.client import Client
from app.ticketing.models.interaction import Interaction
from app.ticketing.models.mail_folder import MailFolder
from app.ticketing.models.rule import Rule
from app.ticketing.models.ticket import Ticket
from app.ticketing.repositories.client_repository import ClientRepository
from app.ticketing.repositories.user_repository import UserRepository
from app.ticketing.services.access_control import (
    ACCOUNT_MANAGER_ROLE_NAME,
    AGENT_ROLE_NAMES,
    CATEGORY_SCOPED_ROLE_NAMES,
    GLOBAL_INBOX_ROLE_NAMES,
    ensure_account_manager_owns_ticket_client,
    ensure_agent_can_view_pending_interaction,
    ensure_agent_can_view_ticket,
    has_permission,
)
from app.ticketing.services.rule_access import (
    RULE_VIEW_ALL_PERMISSION,
    folder_name_to_rules,
)
from app.ticketing.repositories.ticket_scope import ticket_in_categories

logger = logging.getLogger(__name__)

MOVE_PERMISSION = "communication:move_to_folder"
FORWARD_PERMISSION = "communication:reply_external"

# Which RBAC permission each action's manual equivalent requires.
# create_folder has no per-email effect, so no per-email permission.
ACTION_PERMISSIONS: dict[str, str] = {
    RuleActionType.MOVE_TO_FOLDER: MOVE_PERMISSION,
    RuleActionType.FORWARD_TO: FORWARD_PERMISSION,
}


async def load_authorized_user(db, user_id: UUID | None) -> User | None:
    """
    A fully-resolved User for a background job — role, categories and
    the same effective permission set the JWT would carry, computed
    fresh from the database (role defaults + active overrides, via the
    one PermissionResolverService login also uses). Never a stale token
    snapshot, so a revoked permission takes effect on the next check.
    Returns None for a missing or inactive user.
    """

    if user_id is None:
        return None

    user = await UserRepository(db).get_by_id(user_id)
    if user is None or not user.is_active:
        return None

    resolver = PermissionResolverService(
        role_permission_repository=RolePermissionRepository(db),
        permission_override_repository=PermissionOverrideRepository(db),
    )
    permissions, _, scoped_permissions = await resolver.get_effective_permissions(user)

    # Same transient attributes app/dependencies/auth.py attaches.
    user.permissions = permissions
    user.scoped_permissions = scoped_permissions
    user.impersonation_session_id = None
    user.impersonator_id = None
    user.impersonator_name = None
    return user


async def can_act_on_thread(
    *,
    action_type: str,
    root: Interaction,
    ticket: Ticket | None,
    user: User,
    client_repository: ClientRepository,
) -> bool:
    """
    Whether `user` could perform `action_type` by hand on the thread
    rooted at `root` — ownership-level access only (see module
    docstring). Never raises.
    """

    permission = ACTION_PERMISSIONS.get(action_type)
    if permission is None or not has_permission(user, permission):
        return False

    try:
        if action_type == RuleActionType.FORWARD_TO and root.ticket_id is not None:
            if ticket is None:
                return False
            ensure_agent_can_view_ticket(ticket, user)
            await ensure_account_manager_owns_ticket_client(ticket, user, client_repository)
            return True

        # move_to_folder (any status, as the manual Move does) and a
        # pending thread's forward. is_forward_recipient /
        # folder_shared_bypass are left at their False defaults on
        # purpose — no delegated widening.
        await ensure_agent_can_view_pending_interaction(
            root,
            user,
            client_repository,
            permission_backed=permission,
            requires_delegated_access=True,
        )
        return True
    except HTTPException:
        return False


class RunScopeGate:
    """
    Effective run scope = rule owner's authorized scope ∩ triggering
    user's authorized scope, evaluated per thread root and per action.
    Results are cached per (root, action) for the lifetime of one page
    — the worker builds a fresh gate (with freshly loaded users) for
    every page, so revocations are picked up within one page.
    """

    def __init__(self, *, owner: User, trigger: User, db):
        self.owner = owner
        self.trigger = trigger
        self.db = db
        self.client_repository = ClientRepository(db)
        self._cache: dict[tuple[UUID, str], bool] = {}

    @property
    def users(self) -> tuple[User, ...]:
        if self.owner.user_id == self.trigger.user_id:
            return (self.owner,)
        return (self.owner, self.trigger)

    async def allows(self, *, action_type: str, root: Interaction) -> bool:
        key = (root.interaction_id, action_type)
        if key in self._cache:
            return self._cache[key]

        ticket = None
        if root.ticket_id is not None and action_type == RuleActionType.FORWARD_TO:
            ticket = await self.db.get(Ticket, root.ticket_id)

        allowed = True
        for user in self.users:
            if not await can_act_on_thread(
                action_type=action_type,
                root=root,
                ticket=ticket,
                user=user,
                client_repository=self.client_repository,
            ):
                allowed = False
                break

        self._cache[key] = allowed
        return allowed


async def _user_prefilter_clause(db, user: User, root, root_client, root_ticket, ticket_client):
    """
    A SQL predicate on the thread root that is a strict SUPERSET of
    every row can_act_on_thread could ever admit for `user` — used only
    to keep the candidate scan off organization-wide history. It never
    authorizes anything itself: every candidate still goes through
    RunScopeGate. Returns None for "no narrowing" (global-inbox roles,
    whom the gates themselves don't restrict).
    """

    role_name = user.role.name if user.role is not None else None

    if role_name in GLOBAL_INBOX_ROLE_NAMES:
        return None

    if role_name not in AGENT_ROLE_NAMES:
        return false()

    category_ids = await ReportingManagerRepository(db).list_category_ids_by_account_manager(
        user.user_id
    )

    clauses = [
        # Client-mailbox pending gate: the client's owning AM.
        root_client.account_manager_id == user.user_id,
        # Ticketed forward gate for an AM: the ticket's client's AM.
        ticket_client.account_manager_id == user.user_id,
    ]
    if category_ids:
        # Category-mailbox pending gate: a Reporting-Manager AM.
        clauses.append(
            and_(root.client_id.is_(None), root.category_id.in_(list(category_ids)))
        )

    if role_name in CATEGORY_SCOPED_ROLE_NAMES:
        # Ticketed forward gate for Team Lead/Staff: their categories'
        # pool, plus any ticket-scoped ticket:editother_ticket grant.
        category_names = [
            c.category_name for c in (getattr(user, "categories", None) or [])
        ]
        if category_names:
            clauses.append(ticket_in_categories(category_names, root_ticket))
        scoped_ticket_ids = [
            UUID(tid)
            for tid in (getattr(user, "scoped_permissions", None) or {}).get(
                "ticket:editother_ticket", []
            )
        ]
        if scoped_ticket_ids:
            clauses.append(root.ticket_id.in_(scoped_ticket_ids))

    return or_(*clauses)


async def build_scope_prefilter(db, users: Iterable[User]):
    """
    Returns (root_alias, joins, where_clauses) for the candidate query —
    an AND of every user's superset predicate (see
    _user_prefilter_clause). The root is the row itself for a thread
    root, or its parent_interaction_id for a reply (replies are always
    parented directly on the thread root at intake).
    """

    root = aliased(Interaction, name="scope_root")
    root_client = aliased(Client, name="scope_root_client")
    root_ticket = aliased(Ticket, name="scope_root_ticket")
    ticket_client = aliased(Client, name="scope_ticket_client")

    clauses = []
    for user in users:
        clause = await _user_prefilter_clause(
            db, user, root, root_client, root_ticket, ticket_client
        )
        if clause is not None:
            clauses.append(clause)

    return {
        "root": root,
        "root_client": root_client,
        "root_ticket": root_ticket,
        "ticket_client": ticket_client,
        "clauses": clauses,
    }


async def can_use_folder_for_run(
    db,
    *,
    folder: MailFolder | None,
    user: User,
    target_rule_id: UUID | None,
    user_distribution_list_ids: Iterable[UUID],
) -> bool:
    """
    Whether `user` may file historical mail into `folder` — the existing
    folder-visibility model (MailFolderService._is_folder_visible /
    rule:view_all), computed with the rule being run EXCLUDED from the
    folder's referencing rules. Without that exclusion a rule naming
    someone else's private folder would make itself the folder's access
    grant (folder names are global and get-or-create by name). A folder
    that doesn't exist yet is fine: it will be created as this rule's
    own folder.
    """

    if folder is None:
        return True

    if has_permission(user, RULE_VIEW_ALL_PERMISSION):
        return True

    # Deferred import: mail_folder_service imports rule_access, which
    # this module also imports — kept local to avoid a cycle risk.
    from app.ticketing.services.mail_folder_service import _is_folder_visible

    result = await db.execute(select(Rule))
    other_rules = [r for r in result.scalars().all() if r.rule_id != target_rule_id]
    return _is_folder_visible(
        folder, user, folder_name_to_rules(other_rules), user_distribution_list_ids
    )
