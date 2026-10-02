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
    has_attachments: bool = False
    cc_recipients: list[str] = field(default_factory=list)
    attachment_filenames: list[str] = field(default_factory=list)
    attachment_mime_types: list[str] = field(default_factory=list)
    otp_detected: bool = False

    sender_domain: str = field(init=False)

    def __post_init__(self) -> None:
        email = (self.from_email or "").strip().lower()
        self.sender_domain = email.split("@", 1)[1] if "@" in email else ""


def build_rule_email_context(
    *,
    from_email: str | None,
    subject: str | None,
    body: str | None,
    client_id: UUID | None,
    cc: list[str] | None,
    attachments: list[tuple[str, str | None]],
    otp_detected: bool,
) -> RuleEmailContext:
    """
    The one place a RuleEmailContext is assembled — used both by
    EmailService.receive_email (a just-received email) and by "Run rule
    now" (an Interaction already stored), so historical mail is matched
    with exactly the same inputs/normalization the live path uses.
    `attachments` is (filename, mime_type) per stored attachment.
    """

    return RuleEmailContext(
        from_email=from_email,
        subject=subject,
        body=body,
        client_id=client_id,
        has_attachments=bool(attachments),
        cc_recipients=[str(addr).lower() for addr in (cc or []) if addr],
        attachment_filenames=[filename for filename, _ in attachments],
        attachment_mime_types=[mime for _, mime in attachments if mime],
        otp_detected=otp_detected,
    )


def _text_matches(operator: str, haystack: str, needle: str) -> bool:
    haystack = haystack.strip().lower()
    needle = needle.strip().lower()

    if not needle:
        return False

    if operator == RuleConditionOperator.EQUALS:
        return haystack == needle

    # CONTAINS (also the fixed operator for subject_contains/body_contains)
    return needle in haystack


def _text_matches_any(operator: str, haystacks: list[str], needle: str) -> bool:
    return any(_text_matches(operator, haystack, needle) for haystack in haystacks)


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

    if field_name == RuleConditionField.HAS_ATTACHMENT:
        return context.has_attachments == bool(value)

    if field_name == RuleConditionField.RECIPIENT_CC:
        return _text_matches_any(operator, context.cc_recipients, str(value))

    if field_name == RuleConditionField.ATTACHMENT_NAME_CONTAINS:
        return _text_matches_any(operator, context.attachment_filenames, str(value))

    if field_name == RuleConditionField.ATTACHMENT_TYPE_CONTAINS:
        return _text_matches_any(operator, context.attachment_mime_types, str(value))

    if field_name == RuleConditionField.OTP_DETECTED:
        return context.otp_detected == bool(value)

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
