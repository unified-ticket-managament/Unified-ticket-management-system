"""
The one place a rule's create_folder/move_to_folder action gets a
real MailFolder row — idempotent get-or-create by name, reused by
both RuleService (eagerly, right when the rule is saved, so a
configured folder exists and is correctly scoped immediately instead
of waiting for the first matching email) and RuleEngineService
(lazily, at execution time, as a safety net for a rule saved before
this eager path existed, or the rare case a folder was deleted after
the rule that names it was saved). Never create a second, parallel
folder-creation code path — always go through this function.
"""

from uuid import UUID

from app.ticketing.enums.rule_enums import RuleActionType
from app.ticketing.models.mail_folder import MailFolder
from app.ticketing.repositories.mail_folder_repository import MailFolderRepository

_FOLDER_ACTION_TYPES = (RuleActionType.CREATE_FOLDER, RuleActionType.MOVE_TO_FOLDER)


async def ensure_folder(
    folder_name: str,
    *,
    created_by: UUID | None,
    mail_folder_repository: MailFolderRepository,
) -> MailFolder:
    """
    Get-or-create by name. `created_by` is only ever applied when this
    call is the one that actually creates the row — an already-
    existing folder's own created_by is never overwritten (its
    visibility already correctly follows whichever rule(s) currently
    reference it, computed at read time by MailFolderService, not
    baked into this column after creation).
    """

    name = folder_name.strip()
    existing = await mail_folder_repository.get_by_name(name)
    if existing is not None:
        return existing
    return await mail_folder_repository.create(name, created_by=created_by)


def folder_names_from_actions(actions) -> set[str]:
    """
    Extract every create_folder/move_to_folder target folder name from
    a rule's `actions` — accepts either raw JSONB dicts (as stored on
    Rule.actions) or RuleActionItem-shaped objects with `.type`/
    `.folder_name` attributes (as constructed from a request payload).
    """

    names: set[str] = set()
    for action in actions or []:
        if isinstance(action, dict):
            action_type = action.get("type")
            folder_name = action.get("folder_name")
        else:
            action_type = getattr(action, "type", None)
            folder_name = getattr(action, "folder_name", None)

        if action_type not in _FOLDER_ACTION_TYPES:
            continue

        name = (folder_name or "").strip()
        if name:
            names.add(name)

    return names


async def ensure_action_folders(
    actions,
    *,
    created_by: UUID | None,
    mail_folder_repository: MailFolderRepository,
) -> None:
    """Create (idempotently) every folder this rule's actions target."""

    for name in folder_names_from_actions(actions):
        await ensure_folder(
            name, created_by=created_by, mail_folder_repository=mail_folder_repository
        )
