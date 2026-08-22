from uuid import UUID

from fastapi import HTTPException, status
from shared_models.models import User

from app.ticketing.models.rule import Rule
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

RULE_MANAGE_PERMISSION = "rule:manage"


def _ensure_can_view(rule: Rule, current_user: User) -> None:
    if not can_view_rule(rule, current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have access to this rule.",
        )


def _ensure_can_manage(rule: Rule, current_user: User) -> None:
    if not can_manage_rule(rule, current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have access to this rule.",
        )


class RuleService:
    """
    CRUD + ordering for Mail/OTP Rules. No audit logging (mirrors
    MailFolderService's own reasoning — creating/editing an automation
    rule is an org-config action, not a client-communication event);
    execution-time behavior (what a matching rule actually does,
    e.g. actually filing a message into a folder or sending a
    forward) is RuleEngineService's job, not this one's — the one
    exception is eagerly creating a create_folder/move_to_folder
    action's target MailFolder row (see ensure_action_folders) so the
    folder exists, correctly scoped, the instant the rule is saved
    rather than waiting for the first matching email.
    """

    def __init__(
        self,
        rule_repository: RuleRepository,
        mail_folder_repository: MailFolderRepository,
    ):
        self.rule_repository = rule_repository
        self.mail_folder_repository = mail_folder_repository

    async def list_all(self, current_user: User) -> list[RuleResponse]:
        ensure_has_permission(current_user, RULE_MANAGE_PERMISSION)
        if has_permission(current_user, RULE_VIEW_ALL_PERMISSION):
            rules = await self.rule_repository.list_all()
        else:
            rules = await self.rule_repository.list_owned_or_shared(
                current_user.user_id
            )
        return [RuleResponse.model_validate(r) for r in rules]

    async def get(self, rule_id: UUID, current_user: User) -> RuleResponse:
        ensure_has_permission(current_user, RULE_MANAGE_PERMISSION)
        rule = await self._get_or_404(rule_id)
        _ensure_can_view(rule, current_user)
        return RuleResponse.model_validate(rule)

    async def create(self, request: RuleCreate, current_user: User) -> RuleResponse:
        ensure_has_permission(current_user, RULE_MANAGE_PERMISSION)

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

        return RuleResponse.model_validate(created)

    async def update(self, rule_id: UUID, request: RuleUpdate, current_user: User) -> RuleResponse:
        ensure_has_permission(current_user, RULE_MANAGE_PERMISSION)
        rule = await self._get_or_404(rule_id)
        _ensure_can_manage(rule, current_user)

        rule.name = request.name
        rule.is_enabled = request.is_enabled
        rule.conditions = request.conditions.model_dump(mode="json")
        rule.exceptions = request.exceptions.model_dump(mode="json")
        rule.actions = [a.model_dump(mode="json") for a in request.actions]
        rule.stop_processing = request.stop_processing
        rule.shared_user_ids = [str(u) for u in request.shared_user_ids]

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

        return RuleResponse.model_validate(saved)

    async def set_enabled(self, rule_id: UUID, is_enabled: bool, current_user: User) -> RuleResponse:
        ensure_has_permission(current_user, RULE_MANAGE_PERMISSION)
        rule = await self._get_or_404(rule_id)
        _ensure_can_manage(rule, current_user)
        rule.is_enabled = is_enabled
        saved = await self.rule_repository.save(rule)
        return RuleResponse.model_validate(saved)

    async def delete(self, rule_id: UUID, current_user: User) -> None:
        ensure_has_permission(current_user, RULE_MANAGE_PERMISSION)
        rule = await self._get_or_404(rule_id)
        _ensure_can_manage(rule, current_user)

        folder_names = folder_names_from_actions(rule.actions)

        # Computed against every *other* rule before this one is
        # deleted, so "still needed" reflects the state the deletion
        # is about to leave behind — e.g. Rule A and Rule B both file
        # into "Claims Folder"; deleting A must not touch the folder
        # while B still references it.
        still_needed: set[str] = set()
        if folder_names:
            for other in await self.rule_repository.list_all():
                if other.rule_id == rule.rule_id:
                    continue
                still_needed |= folder_names_from_actions(other.actions)

        await self.rule_repository.delete(rule)

        # Same request/transaction as the rule delete above — if this
        # raises, the whole thing (rule delete included) rolls back
        # via get_db's own commit-on-success/rollback-on-exception,
        # rather than leaving the rule gone but its folder orphaned.
        for name in folder_names - still_needed:
            folder = await self.mail_folder_repository.get_by_name(name)
            # created_by is None only for a folder that predates this
            # rule ever existing (or the ownership feature itself) —
            # never delete one of those here, no matter what named it;
            # only a folder this rule-management flow actually owns.
            if folder is not None and folder.created_by is not None:
                await self.mail_folder_repository.delete(folder)

    async def reorder(
        self, rule_id: UUID, request: RuleReorderRequest, current_user: User
    ) -> list[RuleResponse]:
        ensure_has_permission(current_user, RULE_MANAGE_PERMISSION)
        rule = await self._get_or_404(rule_id)
        _ensure_can_manage(rule, current_user)
        siblings = await self.rule_repository.list_by_category_ordered(rule.category)

        index = next(i for i, r in enumerate(siblings) if r.rule_id == rule.rule_id)
        swap_index = index - 1 if request.direction == "up" else index + 1

        if swap_index < 0 or swap_index >= len(siblings):
            # Already at the top/bottom — a no-op, not an error, so the
            # UI's disabled-at-the-edge Up/Down buttons never need to
            # special-case this themselves.
            return [RuleResponse.model_validate(r) for r in siblings]

        neighbor = siblings[swap_index]
        rule.priority, neighbor.priority = neighbor.priority, rule.priority

        await self.rule_repository.save(rule)
        await self.rule_repository.save(neighbor)

        refreshed = await self.rule_repository.list_by_category_ordered(rule.category)
        return [RuleResponse.model_validate(r) for r in refreshed]

    async def _get_or_404(self, rule_id: UUID) -> Rule:
        rule = await self.rule_repository.get_by_id(rule_id)
        if rule is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Rule not found.",
            )
        return rule
