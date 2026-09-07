# test_move_to_folder_permission.py
#
# Decision 6 coverage: communication:move_to_folder gates Move exactly
# the way communication:archive already gates Archive. Bare permission
# holding is still sufficient, ownership aside, as the access_control
# function's own default (requires_delegated_access=False) — but real
# Move-to-Folder/Archive call sites now pass requires_delegated_
# access=True (the frozen-architecture fix: these two used to have NO
# resource/thread-access check at all, letting any permission holder
# act on any interaction system-wide), so a genuine caller additionally
# needs ownership or a legitimate delegated relationship (Manual/Rule
# Forward recipient, or a genuinely shared folder) to this
# interaction's thread. Without the permission at all, the caller
# falls through to the ownership checks regardless. Pure-logic, no DB —
# unit-tests ensure_agent_can_view_pending_interaction directly, same
# convention as test_reply_external_forwarded_recipient_access.py's
# Group B.

from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.ticketing.services.access_control import (
    ensure_agent_can_view_pending_interaction,
)

MOVE_TO_FOLDER = "communication:move_to_folder"


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


async def test_move_allowed_for_holder_regardless_of_ownership_by_default():
    """The bare access_control function still admits on permission
    alone, ownership aside, when a caller doesn't pass requires_
    delegated_access — the backward-compatible default. Real Move-to-
    Folder itself no longer relies on this default (see the next
    test) — InteractionService.set_interaction_folder now explicitly
    opts into requires_delegated_access=True, closing what used to be
    a system-wide "any holder can move any interaction" gap."""

    item = _FakeInteraction(client_id=uuid4())
    am = _FakeUser("Account Manager", permissions=[MOVE_TO_FOLDER])

    # Must not raise, even though `am` owns no client at all here.
    await ensure_agent_can_view_pending_interaction(
        item, am, client_repository=None,
        permission_backed=MOVE_TO_FOLDER,
    )


async def test_move_now_requires_delegated_access_too():
    """Architecture-conformance fix: real Move-to-Folder now passes
    requires_delegated_access=True (mirrors Reply/Archive) — an
    unrelated holder with no ownership/forward/folder-share
    relationship to this specific interaction's thread is denied, but
    the same holder is admitted once genuinely delegated (folder-share
    or forward), exactly like every other action in this pipeline."""

    item = _FakeInteraction(client_id=uuid4())
    am = _FakeUser("Account Manager", permissions=[MOVE_TO_FOLDER])

    with pytest.raises(HTTPException) as exc_info:
        await ensure_agent_can_view_pending_interaction(
            item, am, client_repository=None,
            permission_backed=MOVE_TO_FOLDER,
            requires_delegated_access=True,
        )
    assert exc_info.value.status_code == 403

    await ensure_agent_can_view_pending_interaction(
        item, am, client_repository=None,
        permission_backed=MOVE_TO_FOLDER,
        requires_delegated_access=True,
        folder_shared_bypass=True,
    )


async def test_move_denied_without_the_permission_and_no_ownership():
    """A Team Lead/Staff member (not granted communication:
    move_to_folder by default) with no ownership relationship must be
    denied — the permission is a real gate, not a formality."""

    item = _FakeInteraction(client_id=uuid4())
    stranger = _FakeUser("Staff", permissions=[])

    with pytest.raises(HTTPException) as exc_info:
        await ensure_agent_can_view_pending_interaction(
            item, stranger, client_repository=None,
            permission_backed=MOVE_TO_FOLDER,
        )
    assert exc_info.value.status_code == 403


async def test_move_does_not_get_the_forward_recipient_exception():
    """Move is not scoped down to forward-recipients the way
    communication:reply_external is — holding a different permission
    string (or none) with is_forward_recipient=True must still deny,
    since that carve-out is deliberately reply_external-specific."""

    item = _FakeInteraction(client_id=uuid4())
    user_b = _FakeUser("Staff", permissions=[])

    with pytest.raises(HTTPException) as exc_info:
        await ensure_agent_can_view_pending_interaction(
            item, user_b, client_repository=None,
            permission_backed=MOVE_TO_FOLDER,
            is_forward_recipient=True,
        )
    assert exc_info.value.status_code == 403


async def test_archive_permission_alone_does_not_grant_move():
    """Regression/isolation check: holding communication:archive must
    not also grant Move — these are deliberately separate permissions,
    not aliases of each other."""

    item = _FakeInteraction(client_id=uuid4())
    user = _FakeUser("Account Manager", permissions=["communication:archive"])

    with pytest.raises(HTTPException) as exc_info:
        await ensure_agent_can_view_pending_interaction(
            item, user, client_repository=None,
            permission_backed=MOVE_TO_FOLDER,
        )
    assert exc_info.value.status_code == 403
