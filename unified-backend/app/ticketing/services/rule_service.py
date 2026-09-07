import json
import logging
from typing import Iterable
from uuid import UUID

from fastapi import HTTPException, status
from shared_models.models import User

from app.ticketing.models.rule import Rule
from app.ticketing.repositories.distribution_list_repository import (
    DistributionListRepository,
)
from app.ticketing.repositories.interaction_repository import InteractionRepository
from app.ticketing.repositories.mail_folder_repository import MailFolderRepository
from app.ticketing.repositories.rule_repository import RuleRepository
from app.ticketing.schemas.rule import (
    RuleCreate,
    RuleReorderRequest,
    RuleResponse,
    RuleUpdate,
)
from app.ticketing.services.access_control import ensure_has_permission, has_permission
from app.ticketing.services.rule_access import (
    RULE_VIEW_ALL_PERMISSION,
    can_manage_rule,
    can_view_rule,
)
from app.ticketing.services.rule_folder_sync import (
    ensure_action_folders,
    folder_names_from_actions,
)

# Rule create/update/enable/disable/delete/reorder are system
# administrative config changes, not "ticket-related audit activity" —
# they're deliberately logged into RBAC's own audit_logs table (via
# its AuditLogService), not this domain's ticket_audit_logs, so they
# actually surface in the Centralized Audit Log rather than being
# silently unreachable there (ticket_audit_logs rows require a real
# ticket_id to be retrievable through any existing read path — see
# root CLAUDE.md's audit-log separation section). This is a
# deliberate, one-off cross-module import — app.ticketing importing
# from app.rbac — mirrored already in the opposite direction by
# app.rbac.services.permission_request_service, since both domains are
# one process now.
from app.rbac.repositories.audit_log_repository import AuditLogRepository as RbacAuditLogRepository
from app.rbac.schemas.audit_log import AuditLogCreate as RbacAuditLogCreate
from app.rbac.services.audit_log_service import AuditLogService as RbacAuditLogService

RULE_MANAGE_PERMISSION = "rule:manage"

logger = logging.getLogger(__name__)


def _ensure_can_view(
    rule: Rule, current_user: User, user_distribution_list_ids: Iterable[UUID] = ()
) -> None:
    if not can_view_rule(rule, current_user, user_distribution_list_ids):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have access to this rule.",
        )


def _ensure_can_manage(
    rule: Rule, current_user: User, user_distribution_list_ids: Iterable[UUID] = ()
) -> None:
    if not can_manage_rule(rule, current_user, user_distribution_list_ids):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have access to this rule.",
        )


class RuleService:
    """
    CRUD + ordering for Mail/OTP Rules. Create/update/enable/disable/
    delete/reorder are audit-logged (into RBAC's audit_logs table —
    see the import comment above for why); execution-time behavior
    (what a matching rule actually does, e.g. actually filing a
    message into a folder or sending a forward) is RuleEngineService's
    job, not this one's — the one exception is eagerly creating a
    create_folder/move_to_folder action's target MailFolder row (see
    ensure_action_folders) so the folder exists, correctly scoped, the
    instant the rule is saved rather than waiting for the first
    matching email.
    """

    def __init__(
        self,
        rule_repository: RuleRepository,
        mail_folder_repository: MailFolderRepository,
        distribution_list_repository: DistributionListRepository,
        interaction_repository: InteractionRepository | None = None,
    ):
        self.rule_repository = rule_repository
        self.mail_folder_repository = mail_folder_repository
        self.distribution_list_repository = distribution_list_repository
        self.interaction_repository = interaction_repository

    async def _log_rule_action(
        self,
        *,
        current_user: User,
        action: str,
        entity_id: UUID,
        old_value: dict | None = None,
        new_value: dict | None = None,
    ) -> None:
        audit_log_service = RbacAuditLogService(
            audit_log_repository=RbacAuditLogRepository(self.rule_repository.db)
        )
        await audit_log_service.create_log(
            RbacAuditLogCreate(
                user_id=current_user.user_id,
                action=action,
                entity_type="rule",
                entity_id=str(entity_id),
                old_value=json.dumps(old_value) if old_value is not None else None,
                new_value=json.dumps(new_value) if new_value is not None else None,
            )
        )

    async def _user_distribution_list_ids(self, current_user: User) -> set[UUID]:
        return await self.distribution_list_repository.list_active_list_ids_for_user(
            current_user.user_id
        )

    async def _validate_shared_distribution_lists(
        self, distribution_list_ids: list[UUID]
    ) -> None:
        if not distribution_list_ids:
            return
        found = await self.distribution_list_repository.get_active_by_ids(
            distribution_list_ids
        )
        found_ids = {dl.distribution_list_id for dl in found}
        missing = set(distribution_list_ids) - found_ids
        if missing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="One or more selected Distribution Lists are invalid or inactive.",
            )

    def _to_response(
        self, rule: Rule, current_user: User, user_dl_ids: Iterable[UUID]
    ) -> RuleResponse:
        """
        The one place a `Rule` ORM row becomes a `RuleResponse` with its
        viewer-specific `can_manage` flag correctly attached — reused by
        every method that can return a rule the current viewer didn't
        necessarily create (list_all, reorder), so "can this viewer
        actually edit/delete/toggle/reorder this row" is computed
        identically everywhere rather than re-derived ad hoc.
        """

        response = RuleResponse.model_validate(rule)
        response.can_manage = can_manage_rule(rule, current_user, user_dl_ids)
        return response

    async def _visible_rules_for_reorder(
        self, category: str, current_user: User, user_dl_ids: Iterable[UUID]
    ) -> list[Rule]:
        """
        The exact same visibility scope `list_all` uses for this caller,
        narrowed to one category and priority-ordered — this is what
        reorder()'s own adjacency math needs to agree with, since the
        frontend's Up/Down buttons are indexed against precisely this
        same list (via GET /rules). Using the unscoped
        list_by_category_ordered here for every caller (the previous
        behavior) let a non-view-all user's "adjacent" rule differ from
        what they were actually shown, silently swapping the wrong pair.
        """

        if has_permission(current_user, RULE_VIEW_ALL_PERMISSION):
            return await self.rule_repository.list_by_category_ordered(category)
        owned_or_shared = await self.rule_repository.list_owned_or_shared(
            current_user.user_id, user_dl_ids
        )
        return sorted(
            (r for r in owned_or_shared if r.category == category),
            key=lambda r: r.priority,
        )

    async def list_all(self, current_user: User) -> list[RuleResponse]:
        ensure_has_permission(current_user, RULE_MANAGE_PERMISSION)
        user_dl_ids = await self._user_distribution_list_ids(current_user)
        if has_permission(current_user, RULE_VIEW_ALL_PERMISSION):
            rules = await self.rule_repository.list_all()
        else:
            rules = await self.rule_repository.list_owned_or_shared(
                current_user.user_id, user_dl_ids
            )
        return [self._to_response(r, current_user, user_dl_ids) for r in rules]

    async def get(self, rule_id: UUID, current_user: User) -> RuleResponse:
        ensure_has_permission(current_user, RULE_MANAGE_PERMISSION)
        rule = await self._get_or_404(rule_id)
        user_dl_ids = await self._user_distribution_list_ids(current_user)
        _ensure_can_view(rule, current_user, user_dl_ids)
        return RuleResponse.model_validate(rule)

    async def create(self, request: RuleCreate, current_user: User) -> RuleResponse:
        ensure_has_permission(current_user, RULE_MANAGE_PERMISSION)
        await self._validate_shared_distribution_lists(
            request.shared_distribution_list_ids
        )

        priority = await self.rule_repository.get_next_priority(request.category)

        rule = Rule(
            name=request.name,
            category=request.category,
            is_enabled=request.is_enabled,
            # mode="json" — plain dict()/model_dump() leaves
            # employee_user_ids as real UUID objects, which asyncpg's
            # JSONB codec can't serialize (TypeError: Object of type
            # UUID is not JSON serializable). mode="json" round-trips
            # everything through JSON-compatible types (UUID -> str)
            # first.
            conditions=request.conditions.model_dump(mode="json"),
            exceptions=request.exceptions.model_dump(mode="json"),
            actions=[a.model_dump(mode="json") for a in request.actions],
            stop_processing=request.stop_processing,
            priority=priority,
            created_by=current_user.user_id,
            shared_user_ids=[str(u) for u in request.shared_user_ids],
            shared_distribution_list_ids=[
                str(dl) for dl in request.shared_distribution_list_ids
            ],
        )

        created = await self.rule_repository.create(rule)

        # Eager, not lazy — the folder exists (correctly scoped to
        # this rule's own owner) the moment the rule is saved, instead
        # of waiting for the next inbound email to happen to match it
        # (which could be minutes away, or never). Idempotent: a
        # folder name shared with another already-existing rule/folder
        # is a no-op get, never a duplicate.
        await ensure_action_folders(
            request.actions,
            created_by=current_user.user_id,
            mail_folder_repository=self.mail_folder_repository,
        )

        await self._log_rule_action(
            current_user=current_user,
            action="rule.create",
            entity_id=created.rule_id,
            new_value={
                "name": created.name,
                "category": created.category,
                "is_enabled": created.is_enabled,
            },
        )

        return RuleResponse.model_validate(created)

    async def update(self, rule_id: UUID, request: RuleUpdate, current_user: User) -> RuleResponse:
        ensure_has_permission(current_user, RULE_MANAGE_PERMISSION)
        rule = await self._get_or_404(rule_id)
        user_dl_ids = await self._user_distribution_list_ids(current_user)
        _ensure_can_manage(rule, current_user, user_dl_ids)
        await self._validate_shared_distribution_lists(
            request.shared_distribution_list_ids
        )

        old_values = {
            "name": rule.name,
            "is_enabled": rule.is_enabled,
            "stop_processing": rule.stop_processing,
        }

        rule.name = request.name
        rule.is_enabled = request.is_enabled
        rule.conditions = request.conditions.model_dump(mode="json")
        rule.exceptions = request.exceptions.model_dump(mode="json")
        rule.actions = [a.model_dump(mode="json") for a in request.actions]
        rule.stop_processing = request.stop_processing
        rule.shared_user_ids = [str(u) for u in request.shared_user_ids]
        rule.shared_distribution_list_ids = [
            str(dl) for dl in request.shared_distribution_list_ids
        ]

        saved = await self.rule_repository.save(rule)

        # A newly-added folder action needs its folder created right
        # away too — same reasoning as create() above. Owned by the
        # rule's own (unchanged-by-update) created_by, never the
        # editor, since a shared user editing someone else's rule
        # doesn't become the folder's owner.
        await ensure_action_folders(
            request.actions,
            created_by=saved.created_by,
            mail_folder_repository=self.mail_folder_repository,
        )

        await self._log_rule_action(
            current_user=current_user,
            action="rule.update",
            entity_id=saved.rule_id,
            old_value=old_values,
            new_value={
                "name": saved.name,
                "is_enabled": saved.is_enabled,
                "stop_processing": saved.stop_processing,
            },
        )

        return RuleResponse.model_validate(saved)

    async def set_enabled(self, rule_id: UUID, is_enabled: bool, current_user: User) -> RuleResponse:
        ensure_has_permission(current_user, RULE_MANAGE_PERMISSION)
        rule = await self._get_or_404(rule_id)
        user_dl_ids = await self._user_distribution_list_ids(current_user)
        _ensure_can_manage(rule, current_user, user_dl_ids)
        old_is_enabled = rule.is_enabled
        rule.is_enabled = is_enabled
        saved = await self.rule_repository.save(rule)

        await self._log_rule_action(
            current_user=current_user,
            action="rule.enabled" if is_enabled else "rule.disabled",
            entity_id=saved.rule_id,
            old_value={"is_enabled": old_is_enabled},
            new_value={"is_enabled": is_enabled},
        )

        return RuleResponse.model_validate(saved)

    async def delete(self, rule_id: UUID, current_user: User) -> None:
        ensure_has_permission(current_user, RULE_MANAGE_PERMISSION)
        rule = await self._get_or_404(rule_id)
        user_dl_ids = await self._user_distribution_list_ids(current_user)
        _ensure_can_manage(rule, current_user, user_dl_ids)

        logger.info("RULE_DELETE_STARTED rule_id=%s rule_name=%r", rule.rule_id, rule.name)

        old_values = {"name": rule.name, "category": rule.category}
        folder_names = folder_names_from_actions(rule.actions)

        # Computed against every *other* rule before this one is
        # deleted, so "still needed" reflects the state the deletion
        # is about to leave behind — e.g. Rule A and Rule B both file
        # into "Claims Folder"; deleting A must not touch the folder
        # while B still references it. Sharing (shared_user_ids/
        # shared_distribution_list_ids) is irrelevant here — this is
        # purely "does any other rule's own actions still name this
        # folder," regardless of who can see either rule.
        still_needed: set[str] = set()
        if folder_names:
            for other in await self.rule_repository.list_all():
                if other.rule_id == rule.rule_id:
                    continue
                still_needed |= folder_names_from_actions(other.actions)

        for name in folder_names & still_needed:
            folder = await self.mail_folder_repository.get_by_name(name)
            if folder is not None:
                logger.info(
                    "RULE_FOLDER_PRESERVED folder_id=%s folder_name=%r "
                    'reason="referenced_by_other_rule"',
                    folder.folder_id,
                    name,
                )

        await self.rule_repository.delete(rule)

        await self._log_rule_action(
            current_user=current_user,
            action="rule.delete",
            entity_id=rule_id,
            old_value=old_values,
        )

        # Same request/transaction as the rule delete above — if
        # anything below raises, the whole thing (rule delete
        # included) rolls back via get_db's own commit-on-success/
        # rollback-on-exception, rather than leaving a partially-
        # deleted state (rule gone but folder/messages inconsistent).
        for name in folder_names - still_needed:
            folder = await self.mail_folder_repository.get_by_name(name)
            if folder is None:
                continue

            # The real ownership signal: only a folder rule_folder_sync.
            # ensure_folder actually created is eligible for automatic
            # cleanup here. A folder a user created by hand (POST
            # /folders — created_by set, is_rule_created left False)
            # is never auto-deleted, no matter what a rule's own
            # actions happened to name it, or how many messages it
            # holds — it's the user's folder, not this rule's.
            if not folder.is_rule_created:
                logger.info(
                    "RULE_FOLDER_PRESERVED folder_id=%s folder_name=%r "
                    'reason="not_rule_created"',
                    folder.folder_id,
                    name,
                )
                continue

            # This folder is exclusively owned by the rule just
            # deleted. MailFolder has no ON DELETE CASCADE from
            # interactions.folder_id (interactions_folder_id_fkey), so
            # deleting it while real messages are still filed under it
            # would raise an unhandled ForeignKeyViolationError — and,
            # more importantly, those messages must never be lost.
            # Unfile them first (folder_id -> NULL, never touching the
            # interaction row itself, its ticket_id, attachments, or
            # audit history) so they fall back to the normal Inbox,
            # then delete the now-empty folder.
            if self.interaction_repository is None:
                # No interaction_repository was wired into this
                # RuleService instance — refuse to delete a folder we
                # can't safely unfile messages from first, rather than
                # risking either an FK crash or, worse, silently
                # deleting messages. Every real API call site wires
                # this in; only a caller that deliberately omits it
                # (e.g. a narrowly-scoped test) hits this branch.
                logger.warning(
                    "RULE_FOLDER_PRESERVED folder_id=%s folder_name=%r "
                    'reason="no_interaction_repository"',
                    folder.folder_id,
                    name,
                )
                continue

            affected = await self.interaction_repository.clear_folder_for_folder_id(
                folder.folder_id
            )
            logger.info(
                "RULE_FOLDER_CLEANUP rule_id=%s folder_id=%s folder_name=%r "
                "affected_interaction_count=%s",
                rule_id,
                folder.folder_id,
                name,
                affected,
            )

            await self.mail_folder_repository.delete(folder)
            logger.info("RULE_FOLDER_DELETED folder_id=%s folder_name=%r", folder.folder_id, name)

        logger.info("RULE_DELETE_COMPLETED rule_id=%s", rule_id)

    async def reorder(
        self, rule_id: UUID, request: RuleReorderRequest, current_user: User
    ) -> list[RuleResponse]:
        ensure_has_permission(current_user, RULE_MANAGE_PERMISSION)
        rule = await self._get_or_404(rule_id)
        user_dl_ids = await self._user_distribution_list_ids(current_user)
        _ensure_can_manage(rule, current_user, user_dl_ids)
        siblings = await self._visible_rules_for_reorder(
            rule.category, current_user, user_dl_ids
        )

        index = next(i for i, r in enumerate(siblings) if r.rule_id == rule.rule_id)
        swap_index = index - 1 if request.direction == "up" else index + 1

        if swap_index < 0 or swap_index >= len(siblings):
            # Already at the top/bottom — a no-op, not an error, so the
            # UI's disabled-at-the-edge Up/Down buttons never need to
            # special-case this themselves.
            return [
                self._to_response(r, current_user, user_dl_ids) for r in siblings
            ]

        neighbor = siblings[swap_index]
        if not can_manage_rule(neighbor, current_user, user_dl_ids):
            # Distinct from _ensure_can_manage's shared message — this
            # is specifically about the *other* rule being swapped
            # with, not the one the user clicked Up/Down on. Without
            # this check, a rule:view_all holder could otherwise mutate
            # another user's un-owned, unshared rule's priority just by
            # reordering their own rule next to it.
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Couldn't reorder past a rule you don't have access to.",
            )
        rule.priority, neighbor.priority = neighbor.priority, rule.priority

        await self.rule_repository.save(rule)
        await self.rule_repository.save(neighbor)

        await self._log_rule_action(
            current_user=current_user,
            action="rule.reordered",
            entity_id=rule.rule_id,
            new_value={"direction": request.direction, "rule_id": str(rule_id)},
        )

        refreshed = await self._visible_rules_for_reorder(
            rule.category, current_user, user_dl_ids
        )
        return [self._to_response(r, current_user, user_dl_ids) for r in refreshed]

    async def _get_or_404(self, rule_id: UUID) -> Rule:
        rule = await self.rule_repository.get_by_id(rule_id)
        if rule is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Rule not found.",
            )
        return rule
