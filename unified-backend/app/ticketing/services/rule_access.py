"""
Shared "can this user view/manage this rule" checks — the single
source of truth for rule ownership/sharing, reused by both
RuleService (rule CRUD itself) and MailFolderService (a rule-created
folder's visibility is derived from whether the viewer can view the
rule(s) that file mail into it). Do not reimplement this check a
second time anywhere else.
"""

from typing import Iterable
from uuid import UUID

from shared_models.models import User

from app.ticketing.models.rule import Rule
from app.ticketing.services.access_control import has_permission
from app.ticketing.services.rule_folder_sync import folder_names_from_actions

# View-only widening: a holder can see every rule (and every folder a
# rule files mail into) regardless of ownership/sharing, but this
# never grants edit/delete/reorder rights on a rule they don't own or
# aren't shared on — see can_manage_rule, which deliberately never
# checks this permission.
RULE_VIEW_ALL_PERMISSION = "rule:view_all"


def _shared_via_distribution_list(
    rule: Rule, user_distribution_list_ids: Iterable[UUID]
) -> bool:
    """
    True if the viewer is a current, active member of any Distribution
    List this rule's shared_distribution_list_ids names — resolved by
    the caller (see DistributionListRepository.list_active_list_ids_for_user)
    and passed in as plain ids, never re-queried here, so this stays a
    pure/no-I/O check like the rest of this module.
    """

    shared_dl_ids = rule.shared_distribution_list_ids or []
    if not shared_dl_ids:
        return False
    return any(str(dl_id) in shared_dl_ids for dl_id in user_distribution_list_ids)


def can_view_rule(
    rule: Rule,
    current_user: User,
    user_distribution_list_ids: Iterable[UUID] = (),
) -> bool:
    return (
        rule.created_by == current_user.user_id
        or str(current_user.user_id) in (rule.shared_user_ids or [])
        or _shared_via_distribution_list(rule, user_distribution_list_ids)
        or has_permission(current_user, RULE_VIEW_ALL_PERMISSION)
    )


def can_manage_rule(
    rule: Rule,
    current_user: User,
    user_distribution_list_ids: Iterable[UUID] = (),
) -> bool:
    return (
        rule.created_by == current_user.user_id
        or str(current_user.user_id) in (rule.shared_user_ids or [])
        or _shared_via_distribution_list(rule, user_distribution_list_ids)
    )


def folder_name_to_rules(all_rules: list[Rule]) -> dict[str, list[Rule]]:
    """
    Every rule in the system (not just ones the current viewer can
    see — a folder's visibility must be checked against whichever
    rule *actually* references it, regardless of who's asking),
    grouped by the folder name(s) its create_folder/move_to_folder
    actions target. The single source of truth for this grouping —
    reused by MailFolderService (folder existence, GET /folders) and
    InboxService (message-level folder-sharing bypass, GET /inbox) so
    the two can never compute "does this rule reference this folder"
    differently.
    """

    mapping: dict[str, list[Rule]] = {}
    for rule in all_rules:
        for name in folder_names_from_actions(rule.actions):
            mapping.setdefault(name, []).append(rule)
    return mapping


def has_folder_share_access(
    folder_name: str,
    current_user: User,
    name_to_rules: dict[str, list[Rule]],
    user_distribution_list_ids: Iterable[UUID] = (),
) -> bool:
    """
    True only when at least one rule that currently files mail into
    folder_name (create_folder/move_to_folder) is can_view_rule-
    visible to this viewer (creator, in shared_user_ids, or
    rule:view_all) — deliberately independent of whether that rule is
    currently enabled, matching GET /folders' own existing behavior
    (RuleRepository.list_all() has no enabled/disabled filter, so a
    disabled-but-shared rule already keeps its folder visible today;
    this bypass must not be stricter than that).

    False when NO rule references the folder at all, even if the
    viewer created the folder itself — that "own, unreferenced
    folder" case must keep using the normal role-scoped ownership
    query, never this bypass (see MailFolderService's own
    "unreferenced folder falls back to created_by" fallback, which
    this function deliberately does not replicate).
    """

    referencing_rules = name_to_rules.get(folder_name)
    if not referencing_rules:
        return False
    return any(
        can_view_rule(r, current_user, user_distribution_list_ids)
        for r in referencing_rules
    )
