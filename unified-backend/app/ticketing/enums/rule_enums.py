"""
Plain string constants for the Mail/OTP Rules engine — deliberately
NOT native Postgres enums (unlike TicketStatus/TicketPriority/etc.),
matching this codebase's existing precedent for fast-moving,
engine-internal vocabulary that never needs a migration to extend
(see RecipientRole in sla_escalation_rules.py for the same pattern).
`Rule.category`/`conditions`/`actions` are plain String/JSONB columns
validated against these constants at the Pydantic schema layer, not
at the database layer.
"""


class RuleCategory:
    MAIL_RULE = "mail_rule"
    OTP_RULE = "otp_rule"

    ALL = (MAIL_RULE, OTP_RULE)


class RuleCombinator:
    AND = "AND"
    OR = "OR"

    ALL = (AND, OR)


class RuleConditionField:
    SENDER_EMAIL = "sender_email"
    SENDER_DOMAIN = "sender_domain"
    SUBJECT_CONTAINS = "subject_contains"
    BODY_CONTAINS = "body_contains"
    CLIENT = "client"
    HAS_ATTACHMENT = "has_attachment"
    RECIPIENT_CC = "recipient_cc"
    ATTACHMENT_NAME_CONTAINS = "attachment_name_contains"
    ATTACHMENT_TYPE_CONTAINS = "attachment_type_contains"
    OTP_DETECTED = "otp_detected"

    ALL = (
        SENDER_EMAIL,
        SENDER_DOMAIN,
        SUBJECT_CONTAINS,
        BODY_CONTAINS,
        CLIENT,
        HAS_ATTACHMENT,
        RECIPIENT_CC,
        ATTACHMENT_NAME_CONTAINS,
        ATTACHMENT_TYPE_CONTAINS,
        OTP_DETECTED,
    )

    # Which condition fields each rule category may use — enforced at
    # the schema layer so a Mail Rule can never smuggle in a
    # forward-only concept and vice versa. HAS_ATTACHMENT/RECIPIENT_CC/
    # ATTACHMENT_NAME_CONTAINS/ATTACHMENT_TYPE_CONTAINS are deliberately
    # Mail-Rule-only — Cc/attachment signals don't fit OTP Rules'
    # recognition/forwarding purpose. Kept as an explicit per-category
    # map rather than one shared tuple so the two never silently drift
    # apart.
    BY_CATEGORY = {
        RuleCategory.MAIL_RULE: (
            SENDER_EMAIL,
            SENDER_DOMAIN,
            SUBJECT_CONTAINS,
            BODY_CONTAINS,
            CLIENT,
            HAS_ATTACHMENT,
            RECIPIENT_CC,
            ATTACHMENT_NAME_CONTAINS,
            ATTACHMENT_TYPE_CONTAINS,
        ),
        RuleCategory.OTP_RULE: (
            OTP_DETECTED,
            SUBJECT_CONTAINS,
            BODY_CONTAINS,
            CLIENT,
        ),
    }

    # Fields whose value is free text matched with an operator picked
    # by the user (equals/contains). subject_contains/body_contains
    # bake the verb into the field name itself, Outlook-style, so they
    # never show an operator picker at all — see RuleConditionOperator.
    TEXT_FIELDS = (SENDER_EMAIL, SENDER_DOMAIN)


class RuleConditionOperator:
    EQUALS = "equals"
    CONTAINS = "contains"
    IN = "in"

    ALL = (EQUALS, CONTAINS, IN)

    # The only operator subject_contains/body_contains/client/etc. are
    # ever evaluated with — not user-selectable for those fields.
    FIXED_BY_FIELD = {
        RuleConditionField.SUBJECT_CONTAINS: CONTAINS,
        RuleConditionField.BODY_CONTAINS: CONTAINS,
        RuleConditionField.CLIENT: IN,
        RuleConditionField.HAS_ATTACHMENT: EQUALS,
        RuleConditionField.RECIPIENT_CC: CONTAINS,
        RuleConditionField.ATTACHMENT_NAME_CONTAINS: CONTAINS,
        RuleConditionField.ATTACHMENT_TYPE_CONTAINS: CONTAINS,
        RuleConditionField.OTP_DETECTED: EQUALS,
    }


class RuleActionType:
    CREATE_FOLDER = "create_folder"
    MOVE_TO_FOLDER = "move_to_folder"
    FORWARD_TO = "forward_to"

    ALL = (CREATE_FOLDER, MOVE_TO_FOLDER, FORWARD_TO)

    BY_CATEGORY = {
        RuleCategory.MAIL_RULE: (CREATE_FOLDER, MOVE_TO_FOLDER, FORWARD_TO),
        RuleCategory.OTP_RULE: (FORWARD_TO,),
    }
