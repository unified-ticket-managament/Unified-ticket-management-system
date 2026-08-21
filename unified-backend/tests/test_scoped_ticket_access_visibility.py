# test_scoped_ticket_access_visibility.py
#
# Coverage for a follow-on gap found after ticket-owner-routed
# Permission Requests shipped: an approved ticket-scoped
# ticket:editother_ticket override already let the grantee ACT on that
# one ticket (reply, change status, etc. — access_control.
# ensure_agent_can_act_on_ticket already handled this), but two things
# were still missing:
#   1. ensure_agent_can_view_ticket (the ticket-detail VIEW gate) had
#      no awareness of a ticket-scoped grant at all, so a Team Lead/
#      Staff member granted access to a ticket OUTSIDE their own
#      category would 403 just clicking into it.
#   2. The ticket-list page's "My Tickets" tab (and its badge count)
#      filtered strictly on Ticket.agent_id == current_user.user_id,
#      so a scoped-grant ticket never showed up there at all, even
#      though the grantee could act on it once they somehow navigated
#      to it directly.
#
# Runs against the real (dev) database inside a transaction that is
# always rolled back at the end, same convention as
# test_permission_request_ticket_owner_routing.py. Run this file in
# isolation, not alongside other DB-touching test files in the same
# pytest process (pre-existing pytest-asyncio event-loop issue
# documented in the root CLAUDE.md).

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from shared_models.models import Category, Role, User

from app.database.session import AsyncSessionLocal, engine
from app.ticketing.enums import TicketPriority
from app.ticketing.models.client import Client
from app.ticketing.models.ticket import Ticket
from app.ticketing.repositories.ticket_repository import TicketRepository
from app.ticketing.services.access_control import ensure_agent_can_view_ticket


# --------------------------------------------------
# Pure unit tests — no DB, no async — for the VIEW gate's new bypass
# --------------------------------------------------


def _stub_user(*, role_name, category_name=None, scoped_permissions=None):
    return SimpleNamespace(
        role=SimpleNamespace(name=role_name),
        category=SimpleNamespace(category_name=SimpleNamespace(value=category_name))
        if category_name is not None
        else None,
        scoped_permissions=scoped_permissions,
    )


def _stub_ticket(*, ticket_type, ticket_id=None):
    return SimpleNamespace(ticket_type=ticket_type, ticket_id=ticket_id or uuid.uuid4())


def test_scoped_grant_bypasses_category_mismatch():
    ticket = _stub_ticket(ticket_type="AR")
    staff = _stub_user(
        role_name="Staff",
        category_name="Referral",
        scoped_permissions={"ticket:editother_ticket": [str(ticket.ticket_id)]},
    )

    # Would 403 on category mismatch (Referral staff, AR ticket)
    # without the scoped grant — must not raise now that they hold it
    # for this exact ticket.
    ensure_agent_can_view_ticket(ticket, staff)


def test_no_scoped_grant_still_blocks_category_mismatch():
    from fastapi import HTTPException

    ticket = _stub_ticket(ticket_type="AR")
    staff = _stub_user(role_name="Staff", category_name="Referral", scoped_permissions={})

    with pytest.raises(HTTPException) as exc_info:
        ensure_agent_can_view_ticket(ticket, staff)
    assert exc_info.value.status_code == 403


def test_scoped_grant_for_a_different_ticket_does_not_leak():
    from fastapi import HTTPException

    ticket = _stub_ticket(ticket_type="AR")
    staff = _stub_user(
        role_name="Staff",
        category_name="Referral",
        scoped_permissions={"ticket:editother_ticket": [str(uuid.uuid4())]},
    )

    with pytest.raises(HTTPException) as exc_info:
        ensure_agent_can_view_ticket(ticket, staff)
    assert exc_info.value.status_code == 403


# --------------------------------------------------
# DB-backed tests — "My Tickets" list/count widening
# --------------------------------------------------


@pytest.fixture
async def db_session():
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.rollback()
    await engine.dispose()


async def _get_role(session, role_name: str) -> Role:
    result = await session.execute(select(Role).where(Role.name == role_name))
    role = result.scalar_one_or_none()
    if role is None:
        pytest.skip(f"Seeded role {role_name!r} not found.")
    return role


async def _get_category(session, category_name: str) -> Category:
    result = await session.execute(select(Category))
    for category in result.scalars().all():
        if category.category_name == category_name:
            return category
    pytest.skip(f"Seeded category {category_name!r} not found.")


async def _make_user(session, *, role: Role, category_id=None, name: str) -> User:
    user = User(
        user_id=uuid.uuid4(),
        name=name,
        email=f"{name.lower().replace(' ', '.')}-{uuid.uuid4().hex[:8]}@example.com",
        password_hash="test-hash-not-a-real-password",
        role_id=role.role_id,
        category_id=category_id,
        is_active=True,
    )
    user.role = role
    session.add(user)
    await session.flush()
    return user


async def _make_ticket(session, *, owner: User, ticket_type: str) -> Ticket:
    client = Client(
        client_id=uuid.uuid4(),
        name=f"Scoped Visibility Test Client {uuid.uuid4().hex[:8]}",
        inbox_email=f"scoped-visibility-test-{uuid.uuid4().hex[:8]}@example.com",
        account_manager_id=owner.user_id,
        is_active=True,
    )
    session.add(client)

    ticket = Ticket(
        ticket_id=uuid.uuid4(),
        client_company_id=client.client_id,
        agent_id=owner.user_id,
        title="Scoped Visibility test ticket",
        ticket_type=ticket_type,
        current_status="OPEN",
        current_priority=TicketPriority.MEDIUM,
        created_at=datetime.now(timezone.utc),
    )
    session.add(ticket)
    await session.flush()
    return ticket


async def test_list_visible_page_mine_includes_scoped_grant_ticket(db_session):
    staff_role = await _get_role(db_session, "Staff")
    category = await _get_category(db_session, "AR")
    other_category = await _get_category(db_session, "Referral")

    owner = await _make_user(
        db_session, role=staff_role, category_id=category.category_id, name="Ticket Owner"
    )
    grantee = await _make_user(
        db_session,
        role=staff_role,
        category_id=other_category.category_id,
        name="Grantee",
    )

    ticket = await _make_ticket(db_session, owner=owner, ticket_type=category.category_name)

    repo = TicketRepository(db_session)

    page = await repo.list_visible_page(
        account_manager_id=None,
        ticket_types=[other_category.category_name],
        limit=20,
        view="mine",
        assigned_to=grantee.user_id,
        viewer_user_id=grantee.user_id,
        scoped_ticket_ids=[ticket.ticket_id],
    )

    returned_ids = {item[0].ticket_id for item in page.items}
    assert ticket.ticket_id in returned_ids

    # Without the scoped grant, the same query must not return it —
    # confirms the widening (not a pre-existing bug) is what's doing
    # the work.
    page_without_grant = await repo.list_visible_page(
        account_manager_id=None,
        ticket_types=[other_category.category_name],
        limit=20,
        view="mine",
        assigned_to=grantee.user_id,
        viewer_user_id=grantee.user_id,
        scoped_ticket_ids=None,
    )
    returned_ids_without_grant = {item[0].ticket_id for item in page_without_grant.items}
    assert ticket.ticket_id not in returned_ids_without_grant


async def test_count_by_view_mine_reflects_scoped_grant_ticket(db_session):
    staff_role = await _get_role(db_session, "Staff")
    category = await _get_category(db_session, "AR")
    other_category = await _get_category(db_session, "Referral")

    owner = await _make_user(
        db_session, role=staff_role, category_id=category.category_id, name="Ticket Owner"
    )
    grantee = await _make_user(
        db_session,
        role=staff_role,
        category_id=other_category.category_id,
        name="Grantee",
    )

    ticket = await _make_ticket(db_session, owner=owner, ticket_type=category.category_name)

    repo = TicketRepository(db_session)

    counts_with_grant = await repo.count_by_view(
        account_manager_id=None,
        ticket_types=[other_category.category_name],
        assigned_to=grantee.user_id,
        viewer_user_id=grantee.user_id,
        scoped_ticket_ids=[ticket.ticket_id],
    )
    counts_without_grant = await repo.count_by_view(
        account_manager_id=None,
        ticket_types=[other_category.category_name],
        assigned_to=grantee.user_id,
        viewer_user_id=grantee.user_id,
        scoped_ticket_ids=None,
    )

    assert counts_with_grant["mine"] == counts_without_grant["mine"] + 1
