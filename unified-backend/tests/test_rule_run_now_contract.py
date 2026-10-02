"""
No-DB checks for "Run rule now" — run in every environment (the
end-to-end suite in test_rule_run_now.py is opt-in, see its docstring).
"""

from types import SimpleNamespace
from uuid import uuid4

from app.ticketing.schemas.rule import RuleCreate, RuleUpdate
from app.ticketing.services.rule_conditions import RuleEmailContext, build_rule_email_context
from app.ticketing.services.rule_run_service import (
    build_precedence_snapshot,
    required_run_permissions,
)

_CONDITIONS = {"combinator": "AND", "rules": [{"field": "sender_email", "operator": "equals", "value": "a@b.com"}]}
_ACTIONS = [{"type": "move_to_folder", "folder_name": "X"}]


def test_run_now_defaults_to_false_on_create_and_update():
    create = RuleCreate(name="r", category="mail_rule", conditions=_CONDITIONS, actions=_ACTIONS)
    update = RuleUpdate(name="r", is_enabled=True, conditions=_CONDITIONS, actions=_ACTIONS)
    assert create.run_now is False
    assert update.run_now is False


def test_run_now_is_not_a_persisted_rule_column():
    from app.ticketing.models.rule import Rule

    assert "run_now" not in Rule.__table__.columns


def test_context_builder_matches_the_previous_inline_construction():
    client_id = uuid4()
    built = build_rule_email_context(
        from_email="Sender@Example.com",
        subject="Hello",
        body="Body",
        client_id=client_id,
        cc=["CC@Example.com"],
        attachments=[("invoice.pdf", "application/pdf"), ("inline.png", None)],
        otp_detected=True,
    )
    expected = RuleEmailContext(
        from_email="Sender@Example.com",
        subject="Hello",
        body="Body",
        client_id=client_id,
        has_attachments=True,
        cc_recipients=["cc@example.com"],
        attachment_filenames=["invoice.pdf", "inline.png"],
        attachment_mime_types=["application/pdf"],
        otp_detected=True,
    )
    assert built == expected


def test_context_builder_tolerates_missing_fields():
    built = build_rule_email_context(
        from_email=None, subject=None, body=None, client_id=None, cc=None, attachments=[], otp_detected=False
    )
    assert built.sender_domain == ""
    assert built.has_attachments is False
    assert built.cc_recipients == []


def _rule(stop: bool, *, enabled_id=None):
    return SimpleNamespace(
        rule_id=enabled_id or uuid4(), name="n", conditions=_CONDITIONS,
        exceptions={"combinator": "AND", "rules": []}, stop_processing=stop,
    )


def test_precedence_snapshot_keeps_only_earlier_stop_processing_rules():
    earlier_stop, earlier_plain, target, later_stop = _rule(True), _rule(False), _rule(True), _rule(True)
    snapshot = build_precedence_snapshot(target, [earlier_stop, earlier_plain, target, later_stop])
    assert [entry["rule_id"] for entry in snapshot] == [str(earlier_stop.rule_id)]


def test_required_permissions_follow_the_manual_actions():
    assert required_run_permissions([{"type": "create_folder", "folder_name": "x"}]) == set()
    assert required_run_permissions(_ACTIONS) == {"communication:move_to_folder"}
    assert required_run_permissions(
        _ACTIONS + [{"type": "forward_to", "employee_user_ids": [str(uuid4())]}]
    ) == {"communication:move_to_folder", "communication:reply_external"}
