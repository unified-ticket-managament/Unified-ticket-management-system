"""
Shared "can this user view/manage this rule" checks — the single
source of truth for rule ownership/sharing, reused by both
RuleService (rule CRUD itself) and MailFolderService (a rule-created
folder's visibility is derived from whether the viewer can view the
rule(s) that file mail into it). Do not reimplement this check a
second time anywhere else.
"""

from shared_models.models import User

from app.ticketing.models.rule import Rule
from app.ticketing.services.access_control import has_permission

# View-only widening: a holder can see every rule (and every folder a
# rule files mail into) regardless of ownership/sharing, but this
# never grants edit/delete/reorder rights on a rule they don't own or
# aren't shared on — see can_manage_rule, which deliberately never
# checks this permission.
RULE_VIEW_ALL_PERMISSION = "rule:view_all"


def can_view_rule(rule: Rule, current_user: User) -> bool:
    return (
        rule.created_by == current_user.user_id
        or str(current_user.user_id) in (rule.shared_user_ids or [])
        or has_permission(current_user, RULE_VIEW_ALL_PERMISSION)
    )


def can_manage_rule(rule: Rule, current_user: User) -> bool:
    return rule.created_by == current_user.user_id or str(
        current_user.user_id
    ) in (rule.shared_user_ids or [])
