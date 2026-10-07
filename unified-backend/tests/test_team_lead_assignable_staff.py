# test_team_lead_assignable_staff.py
#
# Regression coverage for the Create Ticket dialog's "Assigned To ->
# Staff" picker when the actor is a Team Lead. The bug: the Team Lead
# branch of AssignmentService.get_assignable_groups ignored the chosen
# category entirely and only looked at `teamlead_id`, so
#   - a Team Lead's staff in the SELECTED category were not offered when
#     their link was the org-chart `reporting_manager_id` only (the
#     only link a multi-category Team Lead's other-category reports can
#     have — UserService requires staff categories to be a subset of
#     the Team Lead's to set teamlead_id), and
#   - every team member was offered regardless of the selected category.
# resolve_target (the write-path guard) re-uses the same lookup, so a
# crafted agent_id outside the scope is still rejected server-side.
#
# Self-contained world, always rolled back — same convention as
# tests/multi_assignment_support.py.

import uuid

import pytest
from fastapi import HTTPException
from shared_models.models import Category

from app.database.session import AsyncSessionLocal, engine
from app.ticketing.repositories.user_repository import UserRepository
from app.ticketing.services.assignment_service import AssignmentService
from tests.multi_assignment_support import (
    ACCOUNT_MANAGER_PERMISSIONS,
    STAFF_PERMISSIONS,
    TEAM_LEAD_PERMISSIONS,
    _make_user,
    _role,
)


@pytest.fixture
async def db_session():
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.rollback()
    await engine.dispose()


class _World:
    pass


@pytest.fixture
async def w(db_session):
    s = db_session
    w = _World()
    tag = uuid.uuid4().hex[:8]
    staff_role = await _role(s, "Staff")
    tl_role = await _role(s, "Team Lead")
    am_role = await _role(s, "Account Manager")
    sl_role = await _role(s, "Site Lead")

    w.ar = Category(category_id=uuid.uuid4(), category_name=f"AR {tag}")
    w.denials = Category(category_id=uuid.uuid4(), category_name=f"Denials {tag}")
    w.empty = Category(category_id=uuid.uuid4(), category_name=f"Empty {tag}")
    s.add_all([w.ar, w.denials, w.empty])
    await s.flush()

    def mk(name, role, cats, perms):
        return _make_user(s, name=name, role=role, tag=tag, categories=cats, permissions=perms)

    # TL1 spans AR + Denials + Empty (multi-category Team Lead).
    w.tl1 = mk("TL1", tl_role, [w.ar, w.denials, w.empty], TEAM_LEAD_PERMISSIONS)
    w.tl2 = mk("TL2", tl_role, [w.ar], TEAM_LEAD_PERMISSIONS)
    # TL3: no staff linked at all (fallback to own-category staff).
    w.tl3 = mk("TL3", tl_role, [w.ar], TEAM_LEAD_PERMISSIONS)
    w.am = mk("AM", am_role, [], ACCOUNT_MANAGER_PERMISSIONS)
    w.sl = mk("SL", sl_role, [], ACCOUNT_MANAGER_PERMISSIONS)
    await s.flush()

    # AR: A via teamlead_id, B via org-chart link only (teamlead_id unset).
    w.a = mk("StaffA", staff_role, [w.ar], STAFF_PERMISSIONS)
    w.b = mk("StaffB", staff_role, [w.ar], STAFF_PERMISSIONS)
    # Denials: both via org-chart link only.
    w.c = mk("StaffC", staff_role, [w.denials], STAFF_PERMISSIONS)
    w.d = mk("StaffD", staff_role, [w.denials], STAFF_PERMISSIONS)
    # Same category AR but under a DIFFERENT Team Lead -> out of scope.
    w.e = mk("StaffE", staff_role, [w.ar], STAFF_PERMISSIONS)
    # Under TL1 + AR but inactive -> never assignable.
    w.f = mk("StaffF", staff_role, [w.ar], STAFF_PERMISSIONS)
    w.f.is_active = False
    # Under TL1 but in no AR/Denials membership (belongs to Empty-less
    # unrelated category) -> only visible when no category is chosen.
    w.g = mk("StaffG", staff_role, [], STAFF_PERMISSIONS)

    w.a.teamlead_id = w.tl1.user_id
    w.a.reporting_manager_id = w.tl1.user_id
    w.b.reporting_manager_id = w.tl1.user_id
    w.c.reporting_manager_id = w.tl1.user_id
    w.d.reporting_manager_id = w.tl1.user_id
    w.e.teamlead_id = w.tl2.user_id
    w.f.teamlead_id = w.tl1.user_id
    w.g.reporting_manager_id = w.tl1.user_id
    await s.flush()

    w.service = AssignmentService(UserRepository(s))
    return w


async def _staff_ids(service, user, category):
    response = await service.get_assignable_groups(user, category)
    group = next((g for g in response.groups if g.role == "Staff"), None)
    return {u.user_id for u in group.users} if group else set()


async def test_ar_returns_only_ar_staff_in_scope(w):
    # Includes B, whose only link to TL1 is reporting_manager_id.
    assert await _staff_ids(w.service, w.tl1, w.ar.category_name) == {w.a.user_id, w.b.user_id}


async def test_other_category_returns_that_categorys_staff(w):
    assert await _staff_ids(w.service, w.tl1, w.denials.category_name) == {
        w.c.user_id,
        w.d.user_id,
    }


async def test_category_change_changes_the_staff_set(w):
    ar = await _staff_ids(w.service, w.tl1, w.ar.category_name)
    denials = await _staff_ids(w.service, w.tl1, w.denials.category_name)
    assert ar.isdisjoint(denials) and ar and denials


async def test_staff_of_other_team_lead_excluded_even_in_same_category(w):
    assert w.e.user_id not in await _staff_ids(w.service, w.tl1, w.ar.category_name)
    assert await _staff_ids(w.service, w.tl2, w.ar.category_name) == {w.e.user_id}


async def test_inactive_staff_excluded(w):
    assert w.f.user_id not in await _staff_ids(w.service, w.tl1, w.ar.category_name)


async def test_category_with_no_staff_is_empty_not_error(w):
    assert await _staff_ids(w.service, w.tl1, w.empty.category_name) == set()


async def test_invalid_category_is_empty_not_error(w):
    assert await _staff_ids(w.service, w.tl1, "No Such Category") == set()


async def test_no_category_keeps_the_unscoped_team_list(w):
    assert await _staff_ids(w.service, w.tl1, None) == {
        w.a.user_id,
        w.b.user_id,
        w.c.user_id,
        w.d.user_id,
        w.g.user_id,
    }


async def test_team_lead_still_gets_only_a_staff_group_and_me(w):
    response = await w.service.get_assignable_groups(w.tl1, w.ar.category_name)
    assert [g.role for g in response.groups] == ["Staff"]
    assert response.me.user_id == w.tl1.user_id


# ---------------------------------------------------------------- write path


async def test_resolve_target_accepts_in_scope_staff(w):
    for staff in (w.a, w.b):
        assert (
            await w.service.resolve_target(w.tl1, staff.user_id, w.ar.category_name)
            == staff.user_id
        )


async def test_resolve_target_accepts_self(w):
    assert (
        await w.service.resolve_target(w.tl1, w.tl1.user_id, w.ar.category_name) == w.tl1.user_id
    )


@pytest.mark.parametrize(
    "who",
    ["e", "f", "c", "tl2", "am"],
    ids=["other-team-same-category", "inactive", "wrong-category", "other-team-lead", "manager"],
)
async def test_resolve_target_rejects_out_of_scope_ids(w, who):
    with pytest.raises(HTTPException) as exc:
        await w.service.resolve_target(w.tl1, getattr(w, who).user_id, w.ar.category_name)
    assert exc.value.status_code == 400


async def test_resolve_target_rejects_unknown_category(w):
    with pytest.raises(HTTPException) as exc:
        await w.service.resolve_target(w.tl1, w.a.user_id, "No Such Category")
    assert exc.value.status_code == 400


# --------------------------------------------------------- other roles intact


async def test_account_manager_and_site_lead_still_see_category_staff_company_wide(w):
    # Unchanged behavior: category-narrowed, not hierarchy-narrowed.
    expected = {w.a.user_id, w.b.user_id, w.e.user_id, w.f.user_id} - {w.f.user_id}
    assert await _staff_ids(w.service, w.am, w.ar.category_name) == expected
    assert await _staff_ids(w.service, w.sl, w.ar.category_name) == expected


async def test_staff_role_gets_no_groups(w):
    response = await w.service.get_assignable_groups(w.a, w.ar.category_name)
    assert response.groups == []
    assert response.me.user_id == w.a.user_id


# ------------------------------------------------ Team Lead with no team


async def test_unlinked_team_lead_falls_back_to_active_staff_in_own_category(w):
    # Everyone active in AR, regardless of which Team Lead they report to;
    # inactive F excluded; Denials-only staff excluded.
    assert await _staff_ids(w.service, w.tl3, w.ar.category_name) == {
        w.a.user_id,
        w.b.user_id,
        w.e.user_id,
    }


async def test_unlinked_team_lead_gets_nothing_for_a_category_they_are_not_in(w):
    assert await _staff_ids(w.service, w.tl3, w.denials.category_name) == set()
    assert await _staff_ids(w.service, w.tl3, "No Such Category") == set()


async def test_unlinked_team_lead_write_path_matches_the_fallback(w):
    assert (
        await w.service.resolve_target(w.tl3, w.e.user_id, w.ar.category_name) == w.e.user_id
    )
    for bad in (w.c, w.f):  # wrong category / inactive
        with pytest.raises(HTTPException):
            await w.service.resolve_target(w.tl3, bad.user_id, w.ar.category_name)


async def test_team_lead_with_a_team_does_not_fall_back(w):
    # tl1 has a team; Empty has nobody -> still empty, never widened.
    assert await _staff_ids(w.service, w.tl1, w.empty.category_name) == set()
    assert w.e.user_id not in await _staff_ids(w.service, w.tl1, w.ar.category_name)
