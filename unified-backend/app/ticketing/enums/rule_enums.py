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

    ALL = (SENDER_EMAIL, SENDER_DOMAIN, SUBJECT_CONTAINS, BODY_CONTAINS, CLIENT)

    # Which condition fields each rule category may use — enforced at
    # the schema layer so a Mail Rule can never smuggle in a
    # forward-only concept and vice versa (both categories currently
    # allow the same condition fields; kept as an explicit per-category
    # map rather than one shared tuple so the two never silently drift
    # apart if OTP Rules ever needs a narrower/wider set later).
    BY_CATEGORY = {
        RuleCategory.MAIL_RULE: (
            SENDER_EMAIL,
            SENDER_DOMAIN,
            SUBJECT_CONTAINS,
            BODY_CONTAINS,
            CLIENT,
        ),
        RuleCategory.OTP_RULE: (
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

    # The only operator subject_contains/body_contains/client are ever
    # evaluated with — not user-selectable for those fields.
    FIXED_BY_FIELD = {
        RuleConditionField.SUBJECT_CONTAINS: CONTAINS,
        RuleConditionField.BODY_CONTAINS: CONTAINS,
        RuleConditionField.CLIENT: IN,
    }


class RuleActionType:
    CREATE_FOLDER = "create_folder"
    MOVE_TO_FOLDER = "move_to_folder"
    FORWARD_TO = "forward_to"

    ALL = (CREATE_FOLDER, MOVE_TO_FOLDER, FORWARD_TO)

    BY_CATEGORY = {
        RuleCategory.MAIL_RULE: (CREATE_FOLDER, MOVE_TO_FOLDER),
        RuleCategory.OTP_RULE: (FORWARD_TO,),
    }
