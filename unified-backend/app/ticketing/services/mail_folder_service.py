from typing import NamedTuple
from uuid import UUID

from fastapi import HTTPException, status
from shared_models.models import User

from app.ticketing.models.mail_folder import MailFolder
from app.ticketing.models.rule import Rule
from app.ticketing.repositories.mail_folder_repository import MailFolderRepository
from app.ticketing.repositories.rule_repository import RuleRepository
from app.ticketing.schemas.mail_folder import MailFolderCreate, MailFolderResponse
from app.ticketing.services.access_control import has_permission
from app.ticketing.services.rule_access import (
    RULE_VIEW_ALL_PERMISSION,
    can_view_rule,
    folder_name_to_rules as _folder_name_to_rules,
    has_folder_share_access,
)


class FolderAccess(NamedTuple):
    visible: bool
    # True only when `visible` is granted via a shared rule's
    # can_view_rule access (has_folder_share_access) rather than the
    # viewer's own created_by fallback or rule:view_all — callers
    # (InboxService) use this to decide whether to widen message-level
    # visibility too, never the reverse.
    via_sharing: bool


def _is_folder_visible(
    folder: MailFolder,
    current_user: User,
    name_to_rules: dict[str, list[Rule]],
) -> bool:
    referencing_rules = name_to_rules.get(folder.name)

    if referencing_rules:
        # The rule is the source of truth once one exists — a
        # folder's own created_by is never consulted here, correctly
        # or not.
        return any(can_view_rule(r, current_user) for r in referencing_rules)

    # No rule anywhere currently names this folder — a manually-
    # created (or orphaned, e.g. its creating rule was since deleted)
    # folder falls back to its own created_by. Deliberately no
    # "created_by IS NULL -> visible to everyone" branch: an unowned,
    # unreferenced folder is private (visible only to a rule:view_all
    # holder, checked by the caller before this function is even
    # reached) by default, never global.
    return folder.created_by == current_user.user_id


class MailFolderService:
    """
    CRUD for custom mail folders (Billing/Claims/General/...). A
    folder's visibility is derived primarily from whichever rule(s)
    currently reference it by name in a create_folder/move_to_folder
    action (see list_visible/ensure_visible) — the folder's own
    created_by column is irrelevant whenever such a rule exists,
    since the rule is the real source of truth for who's allowed to
    see it. Only a folder no rule references at all falls back to its
    own created_by (visible to that user only, or to a rule:view_all
    holder) — there is deliberately no "created_by IS NULL means
    visible to everyone" case: an unreferenced, unowned folder is
    private by default, never global, matching this feature's own
    "empty share list never means visible to everyone" principle.
    No audit logging here (unlike interaction-level actions):
    creating/deleting a folder is an org-config action, not a
    client-communication event.
    """

    def __init__(self, mail_folder_repository: MailFolderRepository):
        self.mail_folder_repository = mail_folder_repository

    async def list_all(self) -> list[MailFolderResponse]:
        folders = await self.mail_folder_repository.list_all()
        return [MailFolderResponse.model_validate(folder) for folder in folders]

    async def list_visible(
        self, current_user: User, rule_repository: RuleRepository
    ) -> list[MailFolderResponse]:
        if has_permission(current_user, RULE_VIEW_ALL_PERMISSION):
            folders = await self.mail_folder_repository.list_all()
        else:
            all_rules = await rule_repository.list_all()
            name_to_rules = _folder_name_to_rules(all_rules)
            all_folders = await self.mail_folder_repository.list_all()
            folders = [
                f
                for f in all_folders
                if _is_folder_visible(f, current_user, name_to_rules)
            ]
        return [MailFolderResponse.model_validate(folder) for folder in folders]

    async def resolve_folder_access(
        self,
        folder: MailFolder,
        current_user: User,
        rule_repository: RuleRepository,
    ) -> FolderAccess:
        """
        Single-query-set answer to both "can this viewer see this
        folder at all" and "did that access come from a sharing
        grant" — the latter is what InboxService uses to decide
        whether to widen message-level visibility for this one
        folder_id (see that service's own bypass_ownership_scope
        param). rule:view_all grants folder visibility unconditionally
        but is never itself a "sharing" grant in the narrower sense
        this method's `via_sharing` distinguishes.
        """

        if has_permission(current_user, RULE_VIEW_ALL_PERMISSION):
            return FolderAccess(visible=True, via_sharing=False)

        all_rules = await rule_repository.list_all()
        name_to_rules = _folder_name_to_rules(all_rules)

        via_sharing = has_folder_share_access(folder.name, current_user, name_to_rules)
        visible = via_sharing or _is_folder_visible(folder, current_user, name_to_rules)
        return FolderAccess(visible=visible, via_sharing=via_sharing)

    async def ensure_visible(
        self,
        folder: MailFolder,
        current_user: User,
        rule_repository: RuleRepository,
    ) -> None:
        access = await self.resolve_folder_access(folder, current_user, rule_repository)
        if access.visible:
            return

        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Folder not found.",
        )

    async def create(
        self,
        request: MailFolderCreate,
        current_user: User,
    ) -> MailFolderResponse:
        existing = await self.mail_folder_repository.get_by_name(request.name)

        if existing is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A folder with this name already exists.",
            )

        folder = await self.mail_folder_repository.create(
            request.name, current_user.user_id
        )

        return MailFolderResponse.model_validate(folder)

    async def delete(
        self,
        folder_id: UUID,
        current_user: User,
        rule_repository: RuleRepository,
    ) -> None:
        folder = await self.mail_folder_repository.get_by_id(folder_id)

        if folder is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Folder not found.",
            )

        await self.ensure_visible(folder, current_user, rule_repository)

        await self.mail_folder_repository.delete(folder)
