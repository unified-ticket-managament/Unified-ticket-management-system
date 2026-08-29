# test_ticket_view_only_forwarded_access.py
#
# Pure-logic coverage for ensure_agent_can_view_ticket's new
# view_only escape hatch (app/ticketing/services/access_control.py) —
# no DB. Mirrors test_category_mailbox_access_control.py's style for
# the sibling pending-interaction function.
#
# A category-scoped Team Lead/Staff member who was forwarded a mail
# item (or shared the folder it was filed in) could open it right up
# until it became a ticket outside their own category, at which point
# OpenEmailService.get_email_details started 403ing on
# ensure_agent_can_view_ticket with no escape hatch at all — even
# though the exact same communication:view_all permission already lets
# them open the identical item before it's ticketed. view_only=True
# closes that gap for the one call site that only ever opens (never
# mutates) a ticket; every other caller never passes it.

from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.ticketing.services.access_control import ensure_agent_can_view_ticket


class _FakeRole:
    def __init__(self, name):
        self.name = name


class _FakeCategory:
    def __init__(self, category_name):
        self.category_name = category_name


class _FakeUser:
    def __init__(self, role_name, categories=(), permissions=None, scoped_permissions=None):
        self.user_id = uuid4()
        self.role = _FakeRole(role_name)
        self.categories = [_FakeCategory(c) for c in categories]
        self.permissions = permissions or []
        self.scoped_permissions = scoped_permissions or {}


class _FakeTicket:
    def __init__(self, ticket_type):
        self.ticket_id = uuid4()
        self.ticket_type = ticket_type


async def test_view_only_admits_view_all_holder_outside_their_category():
    ticket = _FakeTicket("Payment Posting")
    current_user = _FakeUser(
        "Staff", categories=["AR"], permissions=["communication:view_all"]
    )

    # Must not raise, even though the ticket's category ("Payment
    # Posting") isn't one of this Staff member's own ("AR").
    ensure_agent_can_view_ticket(ticket, current_user, view_only=True)


async def test_view_only_still_rejects_caller_without_view_all():
    ticket = _FakeTicket("Payment Posting")
    current_user = _FakeUser("Staff", categories=["AR"], permissions=[])

    with pytest.raises(HTTPException) as exc_info:
        ensure_agent_can_view_ticket(ticket, current_user, view_only=True)
    assert exc_info.value.status_code == 403


async def test_view_only_defaults_off_every_other_call_site_unaffected():
    """
    Regression guard: reply/transfer/escalate/attachments/SLA and every
    other action call site never passes view_only, so a
    communication:view_all holder outside their own category is still
    rejected there — this widening is opt-in for the one read-only
    call site, never a blanket bypass of category scoping.
    """

    ticket = _FakeTicket("Payment Posting")
    current_user = _FakeUser(
        "Staff", categories=["AR"], permissions=["communication:view_all"]
    )

    with pytest.raises(HTTPException) as exc_info:
        ensure_agent_can_view_ticket(ticket, current_user)
    assert exc_info.value.status_code == 403


async def test_view_only_never_needed_for_own_category():
    ticket = _FakeTicket("AR")
    current_user = _FakeUser("Staff", categories=["AR"], permissions=[])

    # Must not raise regardless of view_only — this is just the
    # pre-existing own-category rule, unaffected by the new param.
    ensure_agent_can_view_ticket(ticket, current_user)
    ensure_agent_can_view_ticket(ticket, current_user, view_only=True)
