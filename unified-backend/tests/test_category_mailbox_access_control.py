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
    def __init__(self, user_id, role_name):
        self.user_id = user_id
        self.role = _FakeRole(role_name)


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
