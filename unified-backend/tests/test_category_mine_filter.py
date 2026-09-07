# test_category_mine_filter.py
#
# Pure-logic coverage (no DB) for GET /categories' new `mine` param
# (app/ticketing/api/category.py's list_categories) — the other half
# of the "All Clients filter leaks other Account Managers' category
# shared inboxes" fix (see root CLAUDE.md's Organization Structure /
# reporting_manager_teams section, and test_category_mailbox_access_
# control.py, which covers the sibling ensure_agent_can_view_pending_
# interaction check using the identical fake/monkeypatch style).
#
# This exercises only the route's role-check + wiring: which
# `category_ids` argument it passes down to CategoryRepository.list_all.
# The SQL filter itself (CategoryRepository.list_all(category_ids=...))
# is covered separately, against a real DB, in
# test_client_category_filter.py.

from uuid import uuid4

from app.ticketing.api.category import list_categories


class _FakeRole:
    def __init__(self, name):
        self.name = name


class _FakeUser:
    def __init__(self, user_id, role_name):
        self.user_id = user_id
        self.role = _FakeRole(role_name)


class _FakeDB:
    pass


class _FakeCategoryRepository:
    """Captures the `category_ids` argument list_categories passes,
    without touching a real database."""

    last_call_category_ids = "UNSET"

    def __init__(self, db):
        self.db = db

    async def list_all(self, category_ids=None):
        _FakeCategoryRepository.last_call_category_ids = category_ids
        return []


class _FakeReportingManagerRepository:
    def __init__(self, db, account_manager_ids_by_category=None):
        self._by_category = account_manager_ids_by_category or {}

    async def list_category_ids_by_account_manager(self, account_manager_id):
        return [
            category_id
            for category_id, am_ids in self._by_category.items()
            if account_manager_id in am_ids
        ]


def _patch_repositories(monkeypatch, *, category_ids_by_am):
    monkeypatch.setattr(
        "app.ticketing.api.category.CategoryRepository", _FakeCategoryRepository
    )
    monkeypatch.setattr(
        "app.rbac.repositories.reporting_manager_repository.ReportingManagerRepository",
        lambda db: _FakeReportingManagerRepository(db, category_ids_by_am),
    )


async def test_mine_false_lists_everything_regardless_of_role(monkeypatch):
    monkeypatch.setattr(
        "app.ticketing.api.category.CategoryRepository", _FakeCategoryRepository
    )

    for role_name in ("Account Manager", "Site Lead", "Team Lead", "Staff", "Super Admin"):
        _FakeCategoryRepository.last_call_category_ids = "UNSET"
        current_user = _FakeUser(uuid4(), role_name)

        await list_categories(mine=False, current_user=current_user, db=_FakeDB())

        assert _FakeCategoryRepository.last_call_category_ids is None


async def test_account_manager_mine_true_gets_only_own_categories(monkeypatch):
    am_id = uuid4()
    own_category = uuid4()
    other_category = uuid4()
    _patch_repositories(
        monkeypatch,
        category_ids_by_am={own_category: [am_id], other_category: [uuid4()]},
    )

    current_user = _FakeUser(am_id, "Account Manager")
    await list_categories(mine=True, current_user=current_user, db=_FakeDB())

    assert _FakeCategoryRepository.last_call_category_ids == [own_category]


async def test_account_manager_mine_true_with_no_mappings_falls_back_to_everything(
    monkeypatch,
):
    # An Account Manager with zero reporting_manager_teams rows is the
    # common case (it's an optional, additive HR layer — see root
    # CLAUDE.md's "Organization Structure" section), not an edge case.
    # `mine=true` used to pass an empty category_ids list here, which
    # CategoryRepository.list_all's `IN (...)` turns into zero rows —
    # silently emptying the Create Ticket category dropdown for most
    # Account Managers. "No HR override configured" should mean default
    # full visibility, not zero categories.
    am_id = uuid4()
    _patch_repositories(monkeypatch, category_ids_by_am={})

    current_user = _FakeUser(am_id, "Account Manager")
    await list_categories(mine=True, current_user=current_user, db=_FakeDB())

    assert _FakeCategoryRepository.last_call_category_ids is None


async def test_non_account_manager_role_mine_true_is_a_no_op(monkeypatch):
    category_id = uuid4()
    am_id = uuid4()
    _patch_repositories(monkeypatch, category_ids_by_am={category_id: [am_id]})

    for role_name in ("Site Lead", "Team Lead", "Staff", "Super Admin"):
        _FakeCategoryRepository.last_call_category_ids = "UNSET"
        current_user = _FakeUser(uuid4(), role_name)

        await list_categories(mine=True, current_user=current_user, db=_FakeDB())

        assert _FakeCategoryRepository.last_call_category_ids is None


async def test_multiple_account_managers_each_get_shared_category(monkeypatch):
    shared_category = uuid4()
    am_one = uuid4()
    am_two = uuid4()
    _patch_repositories(
        monkeypatch, category_ids_by_am={shared_category: [am_one, am_two]}
    )

    await list_categories(
        mine=True, current_user=_FakeUser(am_one, "Account Manager"), db=_FakeDB()
    )
    assert _FakeCategoryRepository.last_call_category_ids == [shared_category]

    await list_categories(
        mine=True, current_user=_FakeUser(am_two, "Account Manager"), db=_FakeDB()
    )
    assert _FakeCategoryRepository.last_call_category_ids == [shared_category]
