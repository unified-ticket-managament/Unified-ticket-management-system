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
