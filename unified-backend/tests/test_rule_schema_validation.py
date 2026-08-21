# test_rule_schema_validation.py
#
# Pydantic-layer validation for Mail/OTP Rule conditions — no database
# needed. Covers the boolean-value requirement for has_attachment and
# the category-scoping that keeps recipient_cc/attachment_name_contains/
# attachment_type_contains/has_attachment Mail-Rule-only.

from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.ticketing.enums.rule_enums import RuleCategory, RuleConditionField, RuleConditionOperator
from app.ticketing.schemas.rule import RuleConditionItem, RuleCreate


class TestHasAttachmentValueValidation:
    def test_boolean_value_is_accepted(self):
        item = RuleConditionItem(
            field=RuleConditionField.HAS_ATTACHMENT,
            operator=RuleConditionOperator.EQUALS,
            value=True,
        )
        assert item.value is True

    def test_string_value_is_rejected(self):
        with pytest.raises(ValidationError):
            RuleConditionItem(
                field=RuleConditionField.HAS_ATTACHMENT,
                operator=RuleConditionOperator.EQUALS,
                value="true",
            )


def _mail_rule_payload(**overrides) -> dict:
    payload = dict(
        name="Route invoices",
        category=RuleCategory.MAIL_RULE,
        is_enabled=True,
        conditions={
            "combinator": "AND",
            "rules": [
                {"field": RuleConditionField.RECIPIENT_CC, "operator": RuleConditionOperator.CONTAINS, "value": "manager@crescenthealth.com"},
            ],
        },
        actions=[{"type": "create_folder", "folder_name": "Invoices"}],
    )
    payload.update(overrides)
    return payload


class TestMailRuleOnlyConditionFields:
    def test_recipient_cc_is_valid_on_a_mail_rule(self):
        rule = RuleCreate(**_mail_rule_payload())
        assert rule.conditions.rules[0].field == RuleConditionField.RECIPIENT_CC

    def test_has_attachment_is_valid_on_a_mail_rule(self):
        rule = RuleCreate(
            **_mail_rule_payload(
                conditions={
                    "combinator": "AND",
                    "rules": [
                        {"field": RuleConditionField.HAS_ATTACHMENT, "operator": RuleConditionOperator.EQUALS, "value": True},
                    ],
                }
            )
        )
        assert rule.conditions.rules[0].field == RuleConditionField.HAS_ATTACHMENT

    def test_attachment_name_contains_is_valid_on_a_mail_rule(self):
        rule = RuleCreate(
            **_mail_rule_payload(
                conditions={
                    "combinator": "AND",
                    "rules": [
                        {"field": RuleConditionField.ATTACHMENT_NAME_CONTAINS, "operator": RuleConditionOperator.CONTAINS, "value": "invoice"},
                    ],
                }
            )
        )
        assert rule.conditions.rules[0].field == RuleConditionField.ATTACHMENT_NAME_CONTAINS

    def test_attachment_type_contains_is_valid_on_a_mail_rule(self):
        rule = RuleCreate(
            **_mail_rule_payload(
                conditions={
                    "combinator": "AND",
                    "rules": [
                        {"field": RuleConditionField.ATTACHMENT_TYPE_CONTAINS, "operator": RuleConditionOperator.CONTAINS, "value": "pdf"},
                    ],
                }
            )
        )
        assert rule.conditions.rules[0].field == RuleConditionField.ATTACHMENT_TYPE_CONTAINS

    @pytest.mark.parametrize(
        "field,operator,value",
        [
            (RuleConditionField.RECIPIENT_CC, RuleConditionOperator.CONTAINS, "manager@crescenthealth.com"),
            (RuleConditionField.HAS_ATTACHMENT, RuleConditionOperator.EQUALS, True),
            (RuleConditionField.ATTACHMENT_NAME_CONTAINS, RuleConditionOperator.CONTAINS, "invoice"),
            (RuleConditionField.ATTACHMENT_TYPE_CONTAINS, RuleConditionOperator.CONTAINS, "pdf"),
        ],
    )
    def test_new_fields_are_rejected_on_an_otp_rule(self, field, operator, value):
        with pytest.raises(ValidationError):
            RuleCreate(
                name="Forward OTP",
                category=RuleCategory.OTP_RULE,
                is_enabled=True,
                conditions={
                    "combinator": "AND",
                    "rules": [{"field": field, "operator": operator, "value": value}],
                },
                actions=[{"type": "forward_to", "employee_user_ids": [str(uuid4())]}],
            )
