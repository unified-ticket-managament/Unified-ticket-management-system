"""
Pure, side-effect-free evaluation of a Mail/OTP Rule's condition (and
exception) tree against one inbound email. No DB access, no I/O — it
only ever reads the RuleEmailContext handed to it, mirroring how
sla_escalation_rules.py's thresholds_reached()/RecipientContext work:
a plain data class in, a plain bool/dict out, unit-testable with zero
fixtures.
"""

from dataclasses import dataclass, field
from uuid import UUID

from app.ticketing.enums.rule_enums import RuleCombinator, RuleConditionField, RuleConditionOperator


@dataclass
class RuleEmailContext:
    from_email: str | None
    subject: str | None
    body: str | None
    client_id: UUID | None

    sender_domain: str = field(init=False)

    def __post_init__(self) -> None:
        email = (self.from_email or "").strip().lower()
        self.sender_domain = email.split("@", 1)[1] if "@" in email else ""


def _text_matches(operator: str, haystack: str, needle: str) -> bool:
    haystack = haystack.strip().lower()
    needle = needle.strip().lower()

    if not needle:
        return False

    if operator == RuleConditionOperator.EQUALS:
        return haystack == needle

    # CONTAINS (also the fixed operator for subject_contains/body_contains)
    return needle in haystack


def _condition_matches(condition, context: RuleEmailContext) -> bool:
    field_name = condition.field
    operator = condition.operator
    value = condition.value

    if field_name == RuleConditionField.SENDER_EMAIL:
        return _text_matches(operator, context.from_email or "", str(value))

    if field_name == RuleConditionField.SENDER_DOMAIN:
        return _text_matches(operator, context.sender_domain, str(value))

    if field_name == RuleConditionField.SUBJECT_CONTAINS:
        return _text_matches(RuleConditionOperator.CONTAINS, context.subject or "", str(value))

    if field_name == RuleConditionField.BODY_CONTAINS:
        return _text_matches(RuleConditionOperator.CONTAINS, context.body or "", str(value))

    if field_name == RuleConditionField.CLIENT:
        if context.client_id is None:
            return False
        allowed = {str(v) for v in value}
        return str(context.client_id) in allowed

    return False


def evaluate_condition_group(group, context: RuleEmailContext) -> bool:
    """
    `group` is a RuleConditionGroup (schemas/rule.py): {combinator, rules}.
    An empty `rules` list never matches — a defensive default so a
    malformed/empty group can't accidentally match every email.
    """

    if not group.rules:
        return False

    results = [_condition_matches(item, context) for item in group.rules]

    if group.combinator == RuleCombinator.OR:
        return any(results)

    return all(results)


def rule_matches(conditions, exceptions, context: RuleEmailContext) -> bool:
    """
    A rule fires when its conditions match AND its exceptions don't
    (Outlook's own "except if" semantics) — an exceptions group with
    zero rules never suppresses anything.
    """

    if not evaluate_condition_group(conditions, context):
        return False

    if exceptions is not None and exceptions.rules and evaluate_condition_group(exceptions, context):
        return False

    return True
