# test_category_mailbox_access_control.py
#
# Pure-logic coverage for ensure_agent_can_view_pending_interaction's
# new CATEGORY-mailbox branch (app/ticketing/services/access_control.py)
# — no DB. A still-pending (pre-ticket) CATEGORY-mailbox interaction
# (client_id is None, category_id is set) must be visible to the
# Account Manager(s) who are Reporting Manager for that category
# (ReportingManagerTeam), and to Site Lead/Super Admin as always —
# never to an unrelated Account Manager, and never to Team Lead/Staff,
# exactly mirroring the pre-existing CLIENT-mailbox rule this branch
# sits alongside.

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
    def __init__(self, user_id, role_name, permissions=None):
        self.user_id = user_id
        self.role = _FakeRole(role_name)
        self.permissions = permissions or []


class _FakeInteraction:
    def __init__(self, client_id=None, category_id=None):
        self.client_id = client_id
        self.category_id = category_id


class _FakeDB:
    pass


class _FakeClientRepository:
    """Only `.db` is read by the category branch; get_by_id is only
    reached by the (untouched) client-mailbox branch, unused here."""

    def __init__(self):
        self.db = _FakeDB()

    async def get_by_id(self, client_id):
        return None


class _FakeReportingManagerRepository:
    def __init__(self, db, account_manager_ids_by_category=None):
        self._by_category = account_manager_ids_by_category or {}

    async def list_account_manager_ids_by_category(self, category_id):
        return list(self._by_category.get(category_id, []))


def _patch_reporting_manager_repository(monkeypatch, account_manager_ids_by_category):
    monkeypatch.setattr(
        "app.rbac.repositories.reporting_manager_repository.ReportingManagerRepository",
        lambda db: _FakeReportingManagerRepository(
            db, account_manager_ids_by_category
        ),
    )


async def test_reporting_manager_can_view_category_mailbox_pending_item(monkeypatch):
    category_id = uuid4()
    account_manager_id = uuid4()
    _patch_reporting_manager_repository(monkeypatch, {category_id: [account_manager_id]})

    interaction = _FakeInteraction(client_id=None, category_id=category_id)
    current_user = _FakeUser(account_manager_id, "Account Manager")

    # Must not raise.
    await ensure_agent_can_view_pending_interaction(
        interaction, current_user, _FakeClientRepository()
    )


async def test_unrelated_account_manager_cannot_view_category_mailbox_pending_item(monkeypatch):
    category_id = uuid4()
    reporting_manager_id = uuid4()
    other_account_manager_id = uuid4()
    _patch_reporting_manager_repository(
        monkeypatch, {category_id: [reporting_manager_id]}
    )

    interaction = _FakeInteraction(client_id=None, category_id=category_id)
    current_user = _FakeUser(other_account_manager_id, "Account Manager")

    with pytest.raises(HTTPException) as exc_info:
        await ensure_agent_can_view_pending_interaction(
            interaction, current_user, _FakeClientRepository()
        )
    assert exc_info.value.status_code == 403


async def test_global_inbox_roles_see_category_mailbox_pending_item_unconditionally(monkeypatch):
    category_id = uuid4()
    _patch_reporting_manager_repository(monkeypatch, {})

    interaction = _FakeInteraction(client_id=None, category_id=category_id)

    for role_name in ("Site Lead", "Super Admin"):
        current_user = _FakeUser(uuid4(), role_name)
        # Must not raise, even though no reporting-manager mapping
        # exists for this category at all.
        await ensure_agent_can_view_pending_interaction(
            interaction, current_user, _FakeClientRepository()
        )


async def test_team_lead_and_staff_cannot_view_category_mailbox_pending_item(monkeypatch):
    """
    Deliberately excluded from both the CLIENT- and CATEGORY-mailbox
    branches, same pre-existing convention this feature doesn't
    change — a pending item only ever belongs to its owning Account
    Manager (by client or by category) until a ticket exists.
    """

    category_id = uuid4()
    account_manager_id = uuid4()
    _patch_reporting_manager_repository(monkeypatch, {category_id: [account_manager_id]})

    interaction = _FakeInteraction(client_id=None, category_id=category_id)

    for role_name in ("Team Lead", "Staff"):
        current_user = _FakeUser(uuid4(), role_name)
        with pytest.raises(HTTPException) as exc_info:
            await ensure_agent_can_view_pending_interaction(
                interaction, current_user, _FakeClientRepository()
            )
        assert exc_info.value.status_code == 403


async def test_client_mailbox_pending_item_unaffected_by_category_branch(monkeypatch):
    """
    Regression guard: a normal CLIENT-mailbox pending item (category_id
    is None) never reaches the new branch at all — proven here by
    wiring a reporting-manager mapping that would wrongly admit the
    caller if the category branch fired, then confirming it still
    403s because this is a client-mailbox item and the fake client
    repository's get_by_id returns None (no owning client found).
    """

    category_id = uuid4()
    account_manager_id = uuid4()
    _patch_reporting_manager_repository(monkeypatch, {category_id: [account_manager_id]})

    interaction = _FakeInteraction(client_id=uuid4(), category_id=None)
    current_user = _FakeUser(account_manager_id, "Account Manager")

    with pytest.raises(HTTPException) as exc_info:
        await ensure_agent_can_view_pending_interaction(
            interaction, current_user, _FakeClientRepository()
        )
    assert exc_info.value.status_code == 403


# --------------------------------------------------------------------
# permission_backed — holding the exact permission an action already
# re-checks afterward (communication:reply_external for Reply/Forward/
# the draft actions, communication:archive for Archive) is sufficient
# on its own to act on a pending item, ownership aside entirely — e.g.
# a Team Lead named in a rule's shared_user_ids for the folder a mail
# item is filed in, holding communication:archive, can archive it even
# though they own neither the client nor the category.
#
# communication:reply_external is narrower: permission alone is no
# longer enough there (see test_reply_external_forwarded_recipient_
# access.py and access_control.ensure_agent_can_view_pending_
# interaction's own docstring) — it also requires `is_forward_
# recipient=True`, confirming this specific pending item was actually
# forwarded to this user (InteractionService._is_forwarded_to_user),
# so the permission can never become a blanket "reply to any pending
# item" grant.
# --------------------------------------------------------------------

async def test_permission_backed_admits_confirmed_forward_recipient(monkeypatch):
    interaction = _FakeInteraction(client_id=uuid4(), category_id=None)
    current_user = _FakeUser(
        uuid4(), "Team Lead", permissions=["communication:reply_external"]
    )

    # Must not raise, even though this Team Lead owns neither the
    # client nor the category — holding the named permission AND being
    # a confirmed forward recipient of this specific item is what
    # admits them here.
    await ensure_agent_can_view_pending_interaction(
        interaction,
        current_user,
        _FakeClientRepository(),
        permission_backed="communication:reply_external",
        is_forward_recipient=True,
    )


async def test_permission_backed_reply_external_alone_no_longer_sufficient(monkeypatch):
    """
    Tightened rule: unlike communication:archive, holding
    communication:reply_external alone (with no confirmed forward-
    recipient relationship to this specific item) must NOT admit a
    non-owner — this is the over-broad "reply to any pending item"
    grant this rule closes. See test_reply_external_forwarded_
    recipient_access.py for the full matrix.
    """

    interaction = _FakeInteraction(client_id=uuid4(), category_id=None)
    current_user = _FakeUser(
        uuid4(), "Team Lead", permissions=["communication:reply_external"]
    )

    with pytest.raises(HTTPException) as exc_info:
        await ensure_agent_can_view_pending_interaction(
            interaction,
            current_user,
            _FakeClientRepository(),
            permission_backed="communication:reply_external",
        )
    assert exc_info.value.status_code == 403


async def test_permission_backed_still_rejects_caller_without_the_named_permission(monkeypatch):
    interaction = _FakeInteraction(client_id=uuid4(), category_id=None)
    current_user = _FakeUser(uuid4(), "Team Lead", permissions=[])

    with pytest.raises(HTTPException) as exc_info:
        await ensure_agent_can_view_pending_interaction(
            interaction,
            current_user,
            _FakeClientRepository(),
            permission_backed="communication:reply_external",
        )
    assert exc_info.value.status_code == 403


async def test_permission_backed_does_not_admit_via_an_unrelated_permission(monkeypatch):
    """
    Holding communication:archive doesn't let you past a call site
    that only defers to communication:reply_external — permission_backed
    checks the exact named permission, not "holds anything."
    """

    interaction = _FakeInteraction(client_id=uuid4(), category_id=None)
    current_user = _FakeUser(
        uuid4(), "Team Lead", permissions=["communication:archive"]
    )

    with pytest.raises(HTTPException) as exc_info:
        await ensure_agent_can_view_pending_interaction(
            interaction,
            current_user,
            _FakeClientRepository(),
            permission_backed="communication:reply_external",
        )
    assert exc_info.value.status_code == 403


async def test_permission_backed_defaults_off_unaffected(monkeypatch):
    """
    Regression guard: claim/tags/folder-assignment never pass
    permission_backed, so holding communication:reply_external doesn't
    help there either — this widening is opt-in per call site, never a
    blanket bypass.
    """

    interaction = _FakeInteraction(client_id=uuid4(), category_id=None)
    current_user = _FakeUser(
        uuid4(), "Team Lead", permissions=["communication:reply_external"]
    )

    with pytest.raises(HTTPException) as exc_info:
        await ensure_agent_can_view_pending_interaction(
            interaction, current_user, _FakeClientRepository()
        )
    assert exc_info.value.status_code == 403
