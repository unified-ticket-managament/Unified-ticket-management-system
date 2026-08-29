# test_ticket_view_only_forwarded_access.py
#
# Pure-logic coverage for ensure_agent_can_view_ticket's view_only
# branch (app/ticketing/services/access_control.py) — no DB. Mirrors
# test_category_mailbox_access_control.py's style for the sibling
# pending-interaction function.
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
#
# Since then, view_only's authorization was rewritten to be driven by
# resolve_communication_visibility_tier (communication:view_all /
# communication:view_assigned) rather than a bare role/category check
# — see the communication-view RBAC fix. This file's
# test_view_only_never_needed_for_own_category used to assert that a
# Staff member holding NEITHER communication permission could still
# open their own category's ticket via view_only=True — that was
# itself the confirmed bug the fix closes (neither permission must
# mean denied, full stop, even for your own category), so that test
# was updated to assert the new, correct 403, with a companion test
# proving access still works once communication:view_assigned is
# actually held.

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


async def test_view_only_never_needed_for_own_category_on_action_call_sites():
    """
    view_only=False (every action call site) is unaffected by the
    communication-permission gate — the pre-existing own-category rule
    still needs no communication permission at all, since reply/
    transfer/escalate/etc. authorize via ticket:*/editown_ticket
    instead.
    """

    ticket = _FakeTicket("AR")
    current_user = _FakeUser("Staff", categories=["AR"], permissions=[])

    # Must not raise.
    ensure_agent_can_view_ticket(ticket, current_user)


async def test_view_only_own_category_denied_without_any_communication_permission():
    """
    Confirmed bug, now fixed: opening a communication (view_only=True)
    used to need no communication:view_* permission at all as long as
    the ticket matched the viewer's own category. A user holding
    NEITHER communication:view_all nor communication:view_assigned
    must be denied here too, even for their own category/own ticket.
    """

    ticket = _FakeTicket("AR")
    current_user = _FakeUser("Staff", categories=["AR"], permissions=[])

    with pytest.raises(HTTPException) as exc_info:
        ensure_agent_can_view_ticket(ticket, current_user, view_only=True)
    assert exc_info.value.status_code == 403


async def test_view_only_own_category_allowed_with_view_assigned():
    """
    The common, correct case: holding communication:view_assigned is
    sufficient to open a communication for your own category's ticket
    — the fix above doesn't overtighten this, only the "neither
    permission" case is newly denied.
    """

    ticket = _FakeTicket("AR")
    current_user = _FakeUser(
        "Staff", categories=["AR"], permissions=["communication:view_assigned"]
    )

    # Must not raise.
    ensure_agent_can_view_ticket(ticket, current_user, view_only=True)
