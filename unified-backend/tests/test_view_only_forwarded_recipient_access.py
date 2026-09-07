# test_view_only_forwarded_recipient_access.py
#
# Phase 2 coverage: ensure_agent_can_view_pending_interaction's
# view_only=True branch now also honors is_forward_recipient=True,
# closing the gap where a forward recipient could already reply to a
# thread (via the action branch's existing is_forward_recipient
# handling) but couldn't open it in the first place without also
# holding communication:view_all or a folder-share. Pure-logic, no DB
# — mirrors test_reply_external_forwarded_recipient_access.py's fake
# conventions.

from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.ticketing.services.access_control import (
    ensure_agent_can_view_pending_interaction,
)


class _FakeRole:
    def __init__(self, name):
        self.name = name


class _FakeUser:
    def __init__(self, role_name, *, permissions=None):
        self.user_id = uuid4()
        self.role = _FakeRole(role_name)
        self.permissions = permissions or []


class _FakeInteraction:
    def __init__(self, *, client_id=None, category_id=None):
        self.interaction_id = uuid4()
        self.client_id = client_id
        self.category_id = category_id


VIEW_ASSIGNED = "communication:view_assigned"
VIEW_ALL = "communication:view_all"


async def test_forward_recipient_can_view_with_only_view_assigned():
    """The new behavior: a forward recipient holding just
    communication:view_assigned (Team Lead/Staff's default tier) can
    now open the thread, with no ownership and no communication:
    view_all — previously this fell through to the ownership checks
    and 403'd."""

    item = _FakeInteraction(client_id=uuid4())
    user_b = _FakeUser("Staff", permissions=[VIEW_ASSIGNED])

    # Must not raise.
    await ensure_agent_can_view_pending_interaction(
        item, user_b, client_repository=None,
        view_only=True,
        is_forward_recipient=True,
    )


async def test_non_forward_recipient_still_denied_view_only():
    """Regression: someone who is NOT a confirmed forward recipient,
    has no ownership, and holds only communication:view_assigned is
    still denied — is_forward_recipient=False must change nothing."""

    item = _FakeInteraction(client_id=uuid4())
    stranger = _FakeUser("Staff", permissions=[VIEW_ASSIGNED])

    with pytest.raises(HTTPException) as exc_info:
        await ensure_agent_can_view_pending_interaction(
            item, stranger, client_repository=None,
            view_only=True,
            is_forward_recipient=False,
        )
    assert exc_info.value.status_code == 403


async def test_forward_recipient_still_denied_with_neither_tier_permission():
    """is_forward_recipient does NOT bypass the tier=='none' hard-reject
    — deliberately consistent with folder_shared_bypass's existing
    precedent, which is checked after the same gate. Holding neither
    communication:view_all nor communication:view_assigned at all is
    still an unconditional deny, even for a confirmed forward
    recipient."""

    item = _FakeInteraction(client_id=uuid4())
    user_b = _FakeUser("Staff", permissions=[])

    with pytest.raises(HTTPException) as exc_info:
        await ensure_agent_can_view_pending_interaction(
            item, user_b, client_repository=None,
            view_only=True,
            is_forward_recipient=True,
        )
    assert exc_info.value.status_code == 403


async def test_view_all_holder_unaffected_by_is_forward_recipient():
    """Regression: a plain communication:view_all holder keeps working
    exactly as before, whether or not is_forward_recipient is set."""

    item = _FakeInteraction(client_id=uuid4())
    am = _FakeUser("Account Manager", permissions=[VIEW_ALL])

    # Not the client's own owning AM, but view_all still lets a non-AM-
    # ceiling role in — Account Manager itself is capped by ownership
    # even under view_all (see the function's own docstring), so use a
    # non-Account-Manager role here to exercise the tier=="all" branch.
    other = _FakeUser("Staff", permissions=[VIEW_ALL])
    await ensure_agent_can_view_pending_interaction(
        item, other, client_repository=None, view_only=True, is_forward_recipient=False,
    )
    await ensure_agent_can_view_pending_interaction(
        item, other, client_repository=None, view_only=True, is_forward_recipient=True,
    )
