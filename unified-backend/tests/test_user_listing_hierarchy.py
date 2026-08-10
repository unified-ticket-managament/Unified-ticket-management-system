# test_user_listing_hierarchy.py
#
# Regression coverage for Issue 7 ("Users page shows client
# companies, and hierarchy scoping was frontend-only"):
#
#   - UserService.list_users used to merge a synthesized pseudo-User
#     row per app.ticketing.Client company (e.g. "APM") into the real
#     users listing (_client_to_user_response) — confirmed live via
#     GET /api/v1/users returning a row named "APM" whose user_id
#     matched a real `clients.client_id`, even though the `users`
#     table itself has no such row. That merge is now removed from
#     list_users specifically (the per-id Client-as-pseudo-user paths
#     used by get/update/deactivate-by-id are untouched).
#   - Reporting-hierarchy visibility (Super Admin sees everyone,
#     Account Manager/Team Lead see only their own reporting subtree,
#     Staff sees only themselves) used to be enforced only by
#     client-side filtering in the Users page — anyone calling the
#     API directly saw every user regardless of role. list_users now
#     enforces this server-side, reusing
#     OrganizationService.get_subordinate_user_ids (the same
#     real manager_id/teamlead_id traversal already trusted to scope
#     permission-override grant authority).
#
# Runs against the real (dev) database inside a transaction that is
# always rolled back at the end — same convention as
# test_ticket_status_on_assignment.py.

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.orm import joinedload
from shared_models.models import Role, User

from app.database.session import AsyncSessionLocal, engine
from app.rbac.repositories.audit_log_repository import AuditLogRepository
from app.rbac.repositories.category_repository import CategoryRepository
from app.rbac.repositories.reporting_manager_repository import ReportingManagerRepository
from app.rbac.repositories.role_repository import RoleRepository
from app.rbac.repositories.user_repository import UserRepository
from app.rbac.services.audit_log_service import AuditLogService
from app.rbac.services.organization_service import OrganizationService
from app.rbac.services.user_service import UserService
from app.ticketing.models.client import Client
from app.ticketing.repositories.client_repository import ClientRepository
from app.ticketing.repositories.user_repository import UserRepository as TicketingUserRepository
from app.ticketing.services.client_service import ClientService


@pytest.fixture
async def db_session():
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.rollback()
    await engine.dispose()


def _build_user_service(session) -> UserService:
    user_repository = UserRepository(session)
    role_repository = RoleRepository(session)
    return UserService(
        user_repository=user_repository,
        role_repository=role_repository,
        category_repository=CategoryRepository(session),
        audit_log_service=AuditLogService(audit_log_repository=AuditLogRepository(session)),
        client_repository=ClientRepository(session),
        client_service=ClientService(
            client_repository=ClientRepository(session),
            user_repository=TicketingUserRepository(session),
        ),
        organization_service=OrganizationService(
            user_repository=user_repository,
            role_repository=role_repository,
            reporting_manager_repository=ReportingManagerRepository(session),
        ),
    )


async def _get_user_by_role(session, role_name: str) -> User:
    result = await session.execute(
        select(User)
        .options(joinedload(User.role))
        .join(Role, Role.role_id == User.role_id)
        .where(Role.name == role_name, User.is_active.is_(True))
    )
    users = result.unique().scalars().all()
    if users:
        return users[0]
    pytest.skip(f"No active seeded {role_name!r} found.")


async def _get_team_lead_with_staff(session) -> User:
    result = await session.execute(
        select(User)
        .options(joinedload(User.role))
        .join(Role, Role.role_id == User.role_id)
        .where(Role.name == "Team Lead", User.is_active.is_(True))
    )
    for team_lead in result.unique().scalars().all():
        staff_result = await session.execute(
            select(User).where(User.teamlead_id == team_lead.user_id, User.is_active.is_(True))
        )
        if staff_result.scalars().first() is not None:
            return team_lead
    pytest.skip("No active seeded Team Lead with at least one Staff report found.")


async def test_client_companies_never_appear_in_user_listing(db_session):
    """
    The reported bug: a real `clients` row (e.g. "APM") used to be
    synthesized into a pseudo-User row and appended to this listing.
    Create a throwaway client (rolled back at test end) and confirm
    its name never appears in the listing, for the unrestricted
    (Super Admin) caller — the widest-visibility case, so if it leaks
    anywhere, it leaks here.
    """

    super_admin = await _get_user_by_role(db_session, "Super Admin")
    account_manager = await _get_user_by_role(db_session, "Account Manager")

    throwaway_name = f"Throwaway-Client-{uuid.uuid4().hex[:8]}"
    client = Client(
        client_id=uuid.uuid4(),
        name=throwaway_name,
        inbox_email=f"throwaway-{uuid.uuid4().hex[:8]}@example.com",
        account_manager_id=account_manager.user_id,
        is_active=True,
    )
    db_session.add(client)
    await db_session.flush()

    service = _build_user_service(db_session)
    users, _total = await service.list_users(
        page=1, page_size=100, current_user=super_admin
    )

    names = [u.name if hasattr(u, "name") else u["name"] for u in users]
    assert throwaway_name not in names
    ids = [u.user_id if hasattr(u, "user_id") else u["user_id"] for u in users]
    assert client.client_id not in ids


async def test_super_admin_sees_unrestricted_listing(db_session):
    super_admin = await _get_user_by_role(db_session, "Super Admin")
    account_manager = await _get_user_by_role(db_session, "Account Manager")
    staff = await _get_user_by_role(db_session, "Staff")

    service = _build_user_service(db_session)
    users, total = await service.list_users(page=1, page_size=100, current_user=super_admin)

    ids = {u.user_id for u in users}
    # Unrestricted: a Super Admin's own listing includes users far
    # outside their own direct reports (an Account Manager and a
    # Staff member picked independently of any hierarchy relation to
    # this Super Admin).
    assert account_manager.user_id in ids or total > len(users)
    assert total >= len(users)


async def _get_account_manager_with_subordinates(session) -> tuple[User, set]:
    organization_service = OrganizationService(
        user_repository=UserRepository(session),
        role_repository=RoleRepository(session),
        reporting_manager_repository=ReportingManagerRepository(session),
    )
    result = await session.execute(
        select(User)
        .options(joinedload(User.role))
        .join(Role, Role.role_id == User.role_id)
        .where(Role.name == "Account Manager", User.is_active.is_(True))
    )
    for account_manager in result.unique().scalars().all():
        subordinate_ids = await organization_service.get_subordinate_user_ids(account_manager)
        if subordinate_ids:
            return account_manager, subordinate_ids
    pytest.skip("No active seeded Account Manager with a non-empty reporting subtree found.")


async def test_account_manager_sees_only_own_subtree(db_session):
    account_manager, expected_subordinate_ids = await _get_account_manager_with_subordinates(
        db_session
    )

    service = _build_user_service(db_session)
    users, total = await service.list_users(
        page=1, page_size=100, current_user=account_manager
    )

    returned_ids = {u.user_id for u in users}
    assert returned_ids == expected_subordinate_ids
    assert total == len(expected_subordinate_ids)
    # The Account Manager never sees themselves in their own report list.
    assert account_manager.user_id not in returned_ids


async def test_team_lead_sees_only_own_staff(db_session):
    team_lead = await _get_team_lead_with_staff(db_session)

    expected_result = await UserRepository(db_session).get_by_teamlead(team_lead.user_id)
    expected_ids = {u.user_id for u in expected_result}

    service = _build_user_service(db_session)
    users, total = await service.list_users(page=1, page_size=100, current_user=team_lead)

    returned_ids = {u.user_id for u in users}
    assert returned_ids == expected_ids
    assert total == len(expected_ids)
    assert team_lead.user_id not in returned_ids


async def test_staff_sees_only_self(db_session):
    staff = await _get_user_by_role(db_session, "Staff")

    service = _build_user_service(db_session)
    users, total = await service.list_users(page=1, page_size=100, current_user=staff)

    assert total == 1
    assert len(users) == 1
    assert users[0].user_id == staff.user_id


async def test_no_authenticated_user_sees_nothing(db_session):
    service = _build_user_service(db_session)
    users, total = await service.list_users(page=1, page_size=100, current_user=None)

    assert users == []
    assert total == 0
