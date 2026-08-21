# test_rule_conditions.py
#
# Pure evaluation-logic tests for the Mail/OTP Rules engine's
# condition/exception tree — no database needed. Mirrors
# test_sla_clock_math.py's own "plain data in, plain bool out" style.

from uuid import uuid4

from app.ticketing.enums.rule_enums import RuleCombinator, RuleConditionField, RuleConditionOperator
from app.ticketing.schemas.rule import RuleConditionGroup
from app.ticketing.services.rule_conditions import RuleEmailContext, rule_matches


def _context(**overrides) -> RuleEmailContext:
    defaults = dict(
        from_email="billing@crescenthealth.com",
        subject="Your monthly invoice",
        body="Please find attached your invoice.",
        client_id=None,
    )
    defaults.update(overrides)
    return RuleEmailContext(**defaults)


def _group(combinator: str, rules: list[dict]) -> RuleConditionGroup:
    return RuleConditionGroup.model_validate({"combinator": combinator, "rules": rules})


class TestSenderDomainCondition:
    def test_equals_matches_exact_domain(self):
        conditions = _group(
            RuleCombinator.AND,
            [{"field": RuleConditionField.SENDER_DOMAIN, "operator": RuleConditionOperator.EQUALS, "value": "crescenthealth.com"}],
        )
        assert rule_matches(conditions, _group(RuleCombinator.AND, []), _context())

    def test_equals_does_not_match_different_domain(self):
        conditions = _group(
            RuleCombinator.AND,
            [{"field": RuleConditionField.SENDER_DOMAIN, "operator": RuleConditionOperator.EQUALS, "value": "otherhealth.com"}],
        )
        assert not rule_matches(conditions, _group(RuleCombinator.AND, []), _context())

    def test_contains_matches_substring(self):
        conditions = _group(
            RuleCombinator.AND,
            [{"field": RuleConditionField.SENDER_DOMAIN, "operator": RuleConditionOperator.CONTAINS, "value": "crescent"}],
        )
        assert rule_matches(conditions, _group(RuleCombinator.AND, []), _context())


class TestSubjectAndBodyContains:
    def test_subject_contains_is_case_insensitive(self):
        conditions = _group(
            RuleCombinator.AND,
            [{"field": RuleConditionField.SUBJECT_CONTAINS, "operator": RuleConditionOperator.CONTAINS, "value": "INVOICE"}],
        )
        assert rule_matches(conditions, _group(RuleCombinator.AND, []), _context())

    def test_body_contains_no_match_returns_false(self):
        conditions = _group(
            RuleCombinator.AND,
            [{"field": RuleConditionField.BODY_CONTAINS, "operator": RuleConditionOperator.CONTAINS, "value": "one time password"}],
        )
        assert not rule_matches(conditions, _group(RuleCombinator.AND, []), _context())


class TestClientCondition:
    def test_client_in_matches_when_id_in_list(self):
        client_id = uuid4()
        conditions = _group(
            RuleCombinator.AND,
            [{"field": RuleConditionField.CLIENT, "operator": RuleConditionOperator.IN, "value": [str(client_id)]}],
        )
        assert rule_matches(conditions, _group(RuleCombinator.AND, []), _context(client_id=client_id))

    def test_client_condition_never_matches_when_email_unmatched(self):
        conditions = _group(
            RuleCombinator.AND,
            [{"field": RuleConditionField.CLIENT, "operator": RuleConditionOperator.IN, "value": [str(uuid4())]}],
        )
        assert not rule_matches(conditions, _group(RuleCombinator.AND, []), _context(client_id=None))


class TestCombinators:
    def test_and_requires_every_condition(self):
        conditions = _group(
            RuleCombinator.AND,
            [
                {"field": RuleConditionField.SENDER_DOMAIN, "operator": RuleConditionOperator.EQUALS, "value": "crescenthealth.com"},
                {"field": RuleConditionField.SUBJECT_CONTAINS, "operator": RuleConditionOperator.CONTAINS, "value": "otp"},
            ],
        )
        assert not rule_matches(conditions, _group(RuleCombinator.AND, []), _context())

    def test_or_requires_only_one_condition(self):
        conditions = _group(
            RuleCombinator.OR,
            [
                {"field": RuleConditionField.SENDER_DOMAIN, "operator": RuleConditionOperator.EQUALS, "value": "somewhereelse.com"},
                {"field": RuleConditionField.SUBJECT_CONTAINS, "operator": RuleConditionOperator.CONTAINS, "value": "invoice"},
            ],
        )
        assert rule_matches(conditions, _group(RuleCombinator.AND, []), _context())

    def test_empty_condition_group_never_matches(self):
        conditions = _group(RuleCombinator.AND, [])
        assert not rule_matches(conditions, _group(RuleCombinator.AND, []), _context())


class TestHasAttachmentCondition:
    def test_true_matches_when_email_has_attachments(self):
        conditions = _group(
            RuleCombinator.AND,
            [{"field": RuleConditionField.HAS_ATTACHMENT, "operator": RuleConditionOperator.EQUALS, "value": True}],
        )
        assert rule_matches(conditions, _group(RuleCombinator.AND, []), _context(has_attachments=True))

    def test_true_does_not_match_when_email_has_no_attachments(self):
        conditions = _group(
            RuleCombinator.AND,
            [{"field": RuleConditionField.HAS_ATTACHMENT, "operator": RuleConditionOperator.EQUALS, "value": True}],
        )
        assert not rule_matches(conditions, _group(RuleCombinator.AND, []), _context(has_attachments=False))

    def test_false_matches_when_email_has_no_attachments(self):
        conditions = _group(
            RuleCombinator.AND,
            [{"field": RuleConditionField.HAS_ATTACHMENT, "operator": RuleConditionOperator.EQUALS, "value": False}],
        )
        assert rule_matches(conditions, _group(RuleCombinator.AND, []), _context(has_attachments=False))


class TestRecipientCcCondition:
    def test_contains_matches_when_cc_address_present(self):
        conditions = _group(
            RuleCombinator.AND,
            [{"field": RuleConditionField.RECIPIENT_CC, "operator": RuleConditionOperator.CONTAINS, "value": "manager@crescenthealth.com"}],
        )
        context = _context(cc_recipients=["manager@crescenthealth.com", "billing@crescenthealth.com"])
        assert rule_matches(conditions, _group(RuleCombinator.AND, []), context)

    def test_contains_is_case_insensitive(self):
        conditions = _group(
            RuleCombinator.AND,
            [{"field": RuleConditionField.RECIPIENT_CC, "operator": RuleConditionOperator.CONTAINS, "value": "MANAGER@crescenthealth.com"}],
        )
        context = _context(cc_recipients=["manager@crescenthealth.com"])
        assert rule_matches(conditions, _group(RuleCombinator.AND, []), context)

    def test_no_match_when_cc_address_absent(self):
        conditions = _group(
            RuleCombinator.AND,
            [{"field": RuleConditionField.RECIPIENT_CC, "operator": RuleConditionOperator.CONTAINS, "value": "manager@crescenthealth.com"}],
        )
        context = _context(cc_recipients=["someoneelse@crescenthealth.com"])
        assert not rule_matches(conditions, _group(RuleCombinator.AND, []), context)


class TestAttachmentNameAndTypeConditions:
    def test_name_contains_matches_a_filename_substring(self):
        conditions = _group(
            RuleCombinator.AND,
            [{"field": RuleConditionField.ATTACHMENT_NAME_CONTAINS, "operator": RuleConditionOperator.CONTAINS, "value": "invoice"}],
        )
        context = _context(attachment_filenames=["March-Invoice.pdf", "notes.txt"])
        assert rule_matches(conditions, _group(RuleCombinator.AND, []), context)

    def test_name_contains_no_match_returns_false(self):
        conditions = _group(
            RuleCombinator.AND,
            [{"field": RuleConditionField.ATTACHMENT_NAME_CONTAINS, "operator": RuleConditionOperator.CONTAINS, "value": "invoice"}],
        )
        context = _context(attachment_filenames=["notes.txt"])
        assert not rule_matches(conditions, _group(RuleCombinator.AND, []), context)

    def test_type_contains_matches_a_mime_type_substring(self):
        conditions = _group(
            RuleCombinator.AND,
            [{"field": RuleConditionField.ATTACHMENT_TYPE_CONTAINS, "operator": RuleConditionOperator.CONTAINS, "value": "pdf"}],
        )
        context = _context(attachment_mime_types=["application/pdf"])
        assert rule_matches(conditions, _group(RuleCombinator.AND, []), context)

    def test_type_contains_no_match_returns_false(self):
        conditions = _group(
            RuleCombinator.AND,
            [{"field": RuleConditionField.ATTACHMENT_TYPE_CONTAINS, "operator": RuleConditionOperator.CONTAINS, "value": "pdf"}],
        )
        context = _context(attachment_mime_types=["image/png"])
        assert not rule_matches(conditions, _group(RuleCombinator.AND, []), context)


class TestExceptions:
    def test_exception_suppresses_an_otherwise_matching_rule(self):
        conditions = _group(
            RuleCombinator.AND,
            [{"field": RuleConditionField.SENDER_DOMAIN, "operator": RuleConditionOperator.EQUALS, "value": "crescenthealth.com"}],
        )
        exceptions = _group(
            RuleCombinator.AND,
            [{"field": RuleConditionField.SUBJECT_CONTAINS, "operator": RuleConditionOperator.CONTAINS, "value": "invoice"}],
        )
        assert not rule_matches(conditions, exceptions, _context())

    def test_empty_exceptions_never_suppress(self):
        conditions = _group(
            RuleCombinator.AND,
            [{"field": RuleConditionField.SENDER_DOMAIN, "operator": RuleConditionOperator.EQUALS, "value": "crescenthealth.com"}],
        )
        assert rule_matches(conditions, _group(RuleCombinator.AND, []), _context())

    def test_non_matching_exception_does_not_suppress(self):
        conditions = _group(
            RuleCombinator.AND,
            [{"field": RuleConditionField.SENDER_DOMAIN, "operator": RuleConditionOperator.EQUALS, "value": "crescenthealth.com"}],
        )
        exceptions = _group(
            RuleCombinator.AND,
            [{"field": RuleConditionField.SUBJECT_CONTAINS, "operator": RuleConditionOperator.CONTAINS, "value": "otp"}],
        )
        assert rule_matches(conditions, exceptions, _context())

    def test_except_if_has_attachment_suppresses_a_matching_rule(self):
        conditions = _group(
            RuleCombinator.AND,
            [{"field": RuleConditionField.SENDER_DOMAIN, "operator": RuleConditionOperator.EQUALS, "value": "crescenthealth.com"}],
        )
        exceptions = _group(
            RuleCombinator.AND,
            [{"field": RuleConditionField.HAS_ATTACHMENT, "operator": RuleConditionOperator.EQUALS, "value": True}],
        )
        assert not rule_matches(conditions, exceptions, _context(has_attachments=True))

    def test_except_if_cc_contains_suppresses_a_matching_rule(self):
        conditions = _group(
            RuleCombinator.AND,
            [{"field": RuleConditionField.SENDER_DOMAIN, "operator": RuleConditionOperator.EQUALS, "value": "crescenthealth.com"}],
        )
        exceptions = _group(
            RuleCombinator.AND,
            [{"field": RuleConditionField.RECIPIENT_CC, "operator": RuleConditionOperator.CONTAINS, "value": "manager@crescenthealth.com"}],
        )
        assert not rule_matches(conditions, exceptions, _context(cc_recipients=["manager@crescenthealth.com"]))

    def test_except_if_attachment_name_contains_suppresses_a_matching_rule(self):
        conditions = _group(
            RuleCombinator.AND,
            [{"field": RuleConditionField.SENDER_DOMAIN, "operator": RuleConditionOperator.EQUALS, "value": "crescenthealth.com"}],
        )
        exceptions = _group(
            RuleCombinator.AND,
            [{"field": RuleConditionField.ATTACHMENT_NAME_CONTAINS, "operator": RuleConditionOperator.CONTAINS, "value": "invoice"}],
        )
        assert not rule_matches(conditions, exceptions, _context(attachment_filenames=["March-Invoice.pdf"]))
