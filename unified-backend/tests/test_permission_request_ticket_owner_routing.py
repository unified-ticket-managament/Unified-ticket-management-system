# test_permission_request_ticket_owner_routing.py
#
# Coverage for ticket-owner routing on the RBAC "Permission Requests"
# system's ticket-scoped ticket:editother_ticket flow: a request scoped
# to a ticket that already has an owner now auto-routes to that owner
# (ignoring any selected_approver_id the client sends), a request
# scoped to an unassigned ticket still falls back to the pre-existing
# manual "Request To" picker, a requester can never end up reviewing
# their own request (at creation or via a later reassignment), and
# reassigning the ticket mid-pending repoints the existing row rather
# than creating a duplicate.
#
# Runs against the real (dev) database inside a transaction that is
# always rolled back at the end — same convention as
# test_internal_note_recipients.py/test_escalation_read_only_access.py.
# Run this file in isolation rather than alongside other DB-touching
# test files in the same pytest process (pre-existing pytest-asyncio
# event-loop issue documented in the root CLAUDE.md, not introduced
# here).

import uuid
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from shared_models.models import Category, Role, User

from app.database.session import AsyncSessionLocal, engine
from app.notifications.repository import NotificationRepository
from app.notifications.service import NotificationService
from app.rbac.repositories import (
    AuditLogRepository,
    PermissionOverrideRepository,
    PermissionRepository,
    PermissionRequestRepository,
    RolePermissionRepository,
    RoleRepository,
    UserRepository as RbacUserRepository,
)
from app.rbac.models.permission_request import PermissionRequestStatus
from app.rbac.schemas.permission_request import (
    PermissionRequestApprove,
    PermissionRequestCreate,
)
from app.rbac.services.audit_log_service import AuditLogService
from app.rbac.services.organization_service import OrganizationService
from app.rbac.services.permission_override_service import PermissionOverrideService
from app.rbac.services.permission_request_service import PermissionRequestService
from app.rbac.services.permission_resolver import PermissionResolverService
from app.ticketing.enums import TicketPriority
from app.ticketing.models.client import Client
from app.ticketing.models.ticket import Ticket
from app.ticketing.repositories.ticket_repository import TicketRepository

TICKET_SCOPED_PERMISSION = "ticket:editother_ticket"


@pytest.fixture
async def db_session():
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.rollback()
    await engine.dispose()


def _build_permission_request_service(session) -> PermissionRequestService:
    role_permission_repository = RolePermissionRepository(session)
    permission_override_repository = PermissionOverrideRepository(session)
    permission_request_repository = PermissionRequestRepository(session)

    permission_resolver = PermissionResolverService(
        role_permission_repository=role_permission_repository,
        permission_override_repository=permission_override_repository,
    )

    organization_service = OrganizationService(
        user_repository=RbacUserRepository(session),
        role_repository=RoleRepository(session),
    )

    audit_log_service = AuditLogService(
        audit_log_repository=AuditLogRepository(session),
    )

    permission_override_service = PermissionOverrideService(
        user_repository=RbacUserRepository(session),
        permission_repository=PermissionRepository(session),
        permission_override_repository=permission_override_repository,
        organization_service=organization_service,
        permission_resolver=permission_resolver,
        audit_log_service=audit_log_service,
        notification_service=NotificationService(NotificationRepository(session)),
    )

    return PermissionRequestService(
        user_repository=RbacUserRepository(session),
        role_repository=RoleRepository(session),
        permission_repository=PermissionRepository(session),
        role_permission_repository=role_permission_repository,
        permission_request_repository=permission_request_repository,
        permission_override_service=permission_override_service,
        permission_resolver=permission_resolver,
        audit_log_service=audit_log_service,
        notification_service=NotificationService(NotificationRepository(session)),
        ticket_repository=TicketRepository(session),
    )


async def _get_role(session, role_name: str) -> Role:
    result = await session.execute(select(Role).where(Role.name == role_name))
    role = result.scalar_one_or_none()
    if role is None:
        pytest.skip(f"Seeded role {role_name!r} not found.")
    return role


async def _get_permission_id(session, permission_name: str):
    permission = await PermissionRepository(session).get_by_name(permission_name)
    if permission is None:
        pytest.skip(f"Seeded permission {permission_name!r} not found.")
    return permission.permission_id


async def _get_category(session, category_name: str) -> Category:
    # Filtered in Python against the enum's own .value rather than in
    # SQL, to sidestep any ambiguity in how the native Postgres enum
    # column compares against a raw string.
    result = await session.execute(select(Category))
    for category in result.scalars().all():
        if category.category_name.value == category_name:
            return category
    pytest.skip(f"Seeded category {category_name!r} not found.")


async def _make_user(
    session,
    *,
    role: Role,
    teamlead_id=None,
    manager_id=None,
    category_id=None,
    name: str,
) -> User:
    user = User(
        user_id=uuid.uuid4(),
        name=name,
        email=f"{name.lower().replace(' ', '.')}-{uuid.uuid4().hex[:8]}@example.com",
        password_hash="test-hash-not-a-real-password",
        role_id=role.role_id,
        teamlead_id=teamlead_id,
        manager_id=manager_id,
        category_id=category_id,
        is_active=True,
    )
    # Set the relationship directly (already-fetched instance) rather
    # than relying on a lazy load, which would raise in this async
    # context — create_request/list_eligible_* both read current_user
    # .role.name.
    user.role = role
    session.add(user)
    await session.flush()
    return user


async def _make_ticket(
    session, *, owner: User | None, ticket_type: str, account_manager: User
) -> tuple[Client, Ticket]:
    # account_manager_id is a real FK into users — always pass a real
    # seeded/test user, never a random UUID, even for an unassigned
    # ticket (owner=None) where there's no agent to default it to.
    client = Client(
        client_id=uuid.uuid4(),
        name=f"Ticket Owner Routing Test Client {uuid.uuid4().hex[:8]}",
        inbox_email=f"owner-routing-test-{uuid.uuid4().hex[:8]}@example.com",
        account_manager_id=account_manager.user_id,
        is_active=True,
    )
    session.add(client)

    ticket = Ticket(
        ticket_id=uuid.uuid4(),
        client_company_id=client.client_id,
        agent_id=owner.user_id if owner is not None else None,
        title="Ticket Owner Routing test ticket",
        ticket_type=ticket_type,
        current_status="OPEN",
        current_priority=TicketPriority.MEDIUM,
        created_at=datetime.now(timezone.utc),
    )
    session.add(ticket)
    await session.flush()
    return client, ticket


@pytest.fixture
async def scenario(db_session):
    """
    Ram (requester) and Pavan (ticket owner) share a Team Lead and a
    category — eligibility is category-based now, not org-hierarchy-
    based, but keeping them under a shared Team Lead here still
    exercises the ordinary/common case. Satish is a second teammate,
    used as a reassignment target.
    """

    staff_role = await _get_role(db_session, "Staff")
    team_lead_role = await _get_role(db_session, "Team Lead")
    category = await _get_category(db_session, "AR")
    other_category = await _get_category(db_session, "Referral")

    # A real Team Lead row to point teamlead_id at (teamlead_id is a
    # genuine FK to users.user_id) — doesn't need to actually manage
    # anyone for this test.
    team_lead = await _make_user(
        db_session, role=team_lead_role, name=f"Test TL {uuid.uuid4().hex[:6]}"
    )

    ram = await _make_user(
        db_session,
        role=staff_role,
        teamlead_id=team_lead.user_id,
        category_id=category.category_id,
        name="Ram",
    )
    pavan = await _make_user(
        db_session,
        role=staff_role,
        teamlead_id=team_lead.user_id,
        category_id=category.category_id,
        name="Pavan",
    )
    satish = await _make_user(
        db_session,
        role=staff_role,
        teamlead_id=team_lead.user_id,
        category_id=category.category_id,
        name="Satish",
    )

    permission_id = await _get_permission_id(db_session, TICKET_SCOPED_PERMISSION)
    service = _build_permission_request_service(db_session)

    return {
        "session": db_session,
        "service": service,
        "permission_id": permission_id,
        "category": category,
        "other_category": other_category,
        "ram": ram,
        "pavan": pavan,
        "satish": satish,
    }


async def test_owned_ticket_auto_routes_to_owner_and_ignores_payload_approver(scenario):
    session, service = scenario["session"], scenario["service"]
    ram, pavan, satish = scenario["ram"], scenario["pavan"], scenario["satish"]

    _, ticket = await _make_ticket(
        session, owner=pavan, ticket_type="AR", account_manager=pavan
    )

    response = await service.create_request(
        current_user=ram,
        request=PermissionRequestCreate(
            permission_id=scenario["permission_id"],
            # Deliberately garbage/wrong — a client cannot smuggle in a
            # different reviewer for an owned ticket.
            selected_approver_id=satish.user_id,
            reason="Need to update the ticket because I am handling this issue.",
            scope_ticket_id=ticket.ticket_id,
        ),
    )

    assert response.selected_approver_id == pavan.user_id
    assert response.selected_approver_id != satish.user_id

    pavan_pending = await service.list_pending_for_review(pavan)
    satish_pending = await service.list_pending_for_review(satish)
    assert any(r.request_id == response.request_id for r in pavan_pending)
    assert not any(r.request_id == response.request_id for r in satish_pending)


async def test_reassignment_resyncs_pending_reviewer_without_duplicating(scenario):
    session, service = scenario["session"], scenario["service"]
    ram, pavan, satish = scenario["ram"], scenario["pavan"], scenario["satish"]

    _, ticket = await _make_ticket(
        session, owner=pavan, ticket_type="AR", account_manager=pavan
    )

    response = await service.create_request(
        current_user=ram,
        request=PermissionRequestCreate(
            permission_id=scenario["permission_id"],
            reason="Need to update the ticket because I am handling this issue.",
            scope_ticket_id=ticket.ticket_id,
        ),
    )
    assert response.selected_approver_id == pavan.user_id

    await service.resync_ticket_scoped_reviewers(ticket.ticket_id, satish.user_id)

    pending_rows = await PermissionRequestRepository(session).list_pending_by_scope_ticket(
        ticket.ticket_id
    )
    assert len(pending_rows) == 1
    assert pending_rows[0].request_id == response.request_id
    assert pending_rows[0].selected_approver_id == satish.user_id

    pavan_pending = await service.list_pending_for_review(pavan)
    satish_pending = await service.list_pending_for_review(satish)
    assert not any(r.request_id == response.request_id for r in pavan_pending)
    assert any(r.request_id == response.request_id for r in satish_pending)


async def test_reassignment_to_requester_leaves_reviewer_unchanged(scenario):
    session, service = scenario["session"], scenario["service"]
    ram, pavan = scenario["ram"], scenario["pavan"]

    _, ticket = await _make_ticket(
        session, owner=pavan, ticket_type="AR", account_manager=pavan
    )

    response = await service.create_request(
        current_user=ram,
        request=PermissionRequestCreate(
            permission_id=scenario["permission_id"],
            reason="Need to update the ticket because I am handling this issue.",
            scope_ticket_id=ticket.ticket_id,
        ),
    )
    assert response.selected_approver_id == pavan.user_id

    # Ram somehow becomes the ticket's new owner — must never become
    # his own reviewer, so the row stays pointed at Pavan.
    await service.resync_ticket_scoped_reviewers(ticket.ticket_id, ram.user_id)

    pending_rows = await PermissionRequestRepository(session).list_pending_by_scope_ticket(
        ticket.ticket_id
    )
    assert len(pending_rows) == 1
    assert pending_rows[0].selected_approver_id == pavan.user_id
    assert pending_rows[0].selected_approver_id != ram.user_id


async def test_unassigned_ticket_falls_back_to_manual_picker(scenario):
    session, service = scenario["session"], scenario["service"]
    ram = scenario["ram"]

    _, ticket = await _make_ticket(
        session, owner=None, ticket_type="AR", account_manager=scenario["pavan"]
    )

    candidates = await service.list_eligible_approver_users(scenario["permission_id"], ram)
    if not candidates:
        pytest.skip("No eligible approver candidates available in this environment.")
    candidate_user, _ = candidates[0]

    response = await service.create_request(
        current_user=ram,
        request=PermissionRequestCreate(
            permission_id=scenario["permission_id"],
            selected_approver_id=candidate_user.user_id,
            reason="Ticket is unassigned but I need to work it.",
            scope_ticket_id=ticket.ticket_id,
        ),
    )

    assert response.selected_approver_id == candidate_user.user_id


async def test_self_request_guard_owner_cannot_request_own_ticket(scenario):
    session, service = scenario["session"], scenario["service"]
    ram, satish = scenario["ram"], scenario["satish"]

    _, ticket = await _make_ticket(
        session, owner=ram, ticket_type="AR", account_manager=ram
    )

    with pytest.raises(HTTPException) as exc_info:
        await service.create_request(
            current_user=ram,
            request=PermissionRequestCreate(
                permission_id=scenario["permission_id"],
                selected_approver_id=satish.user_id,
                reason="Trying to request access to my own ticket.",
                scope_ticket_id=ticket.ticket_id,
            ),
        )

    assert exc_info.value.status_code == 400

    pending_rows = await PermissionRequestRepository(session).list_pending_by_scope_ticket(
        ticket.ticket_id
    )
    assert pending_rows == []


async def test_non_ticket_scoped_request_still_requires_valid_client_approver(scenario):
    session, service = scenario["session"], scenario["service"]
    ram = scenario["ram"]

    candidates = await service.list_eligible_approver_users(scenario["permission_id"], ram)
    if not candidates:
        pytest.skip("No eligible approver candidates available in this environment.")
    candidate_user, _ = candidates[0]

    # A garbage approver id is still rejected for a non-ticket-scoped
    # request — the owner-auto-route branch never applies here.
    with pytest.raises(HTTPException) as exc_info:
        await service.create_request(
            current_user=ram,
            request=PermissionRequestCreate(
                permission_id=scenario["permission_id"],
                selected_approver_id=uuid.uuid4(),
                reason="Need broader access.",
                scope_ticket_id=None,
            ),
        )
    assert exc_info.value.status_code == 400

    response = await service.create_request(
        current_user=ram,
        request=PermissionRequestCreate(
            permission_id=scenario["permission_id"],
            selected_approver_id=candidate_user.user_id,
            reason="Need broader access.",
            scope_ticket_id=None,
        ),
    )
    assert response.selected_approver_id == candidate_user.user_id
    assert response.scope_ticket_id is None


async def test_same_category_allows_request_with_no_shared_supervisor(scenario):
    """
    Mirrors the real-world bug report: two Staff members who share no
    Team Lead, manager, or Account Manager at all — only the same
    category — must still be able to request/route access to each
    other's tickets. Eligibility is category-based only now.
    """
    session, service = scenario["session"], scenario["service"]
    staff_role = await _get_role(session, "Staff")
    account_manager_role = await _get_role(session, "Account Manager")
    category = scenario["category"]

    account_manager_one = await _make_user(
        session, role=account_manager_role, name=f"AM One {uuid.uuid4().hex[:6]}"
    )
    account_manager_two = await _make_user(
        session, role=account_manager_role, name=f"AM Two {uuid.uuid4().hex[:6]}"
    )

    requester = await _make_user(
        session,
        role=staff_role,
        manager_id=account_manager_one.user_id,
        category_id=category.category_id,
        name="Yesudas Test",
    )
    owner = await _make_user(
        session,
        role=staff_role,
        manager_id=account_manager_two.user_id,
        category_id=category.category_id,
        name="Premkumar Test",
    )

    _, ticket = await _make_ticket(
        session,
        owner=owner,
        ticket_type=category.category_name.value,
        account_manager=account_manager_two,
    )

    response = await service.create_request(
        current_user=requester,
        request=PermissionRequestCreate(
            permission_id=scenario["permission_id"],
            reason="Covering while the assigned agent is out.",
            scope_ticket_id=ticket.ticket_id,
        ),
    )

    assert response.selected_approver_id == owner.user_id


async def test_different_category_is_rejected(scenario):
    session, service = scenario["session"], scenario["service"]
    staff_role = await _get_role(session, "Staff")
    pavan = scenario["pavan"]

    requester = await _make_user(
        session,
        role=staff_role,
        category_id=scenario["other_category"].category_id,
        name="Different Category Staff",
    )

    _, ticket = await _make_ticket(
        session, owner=pavan, ticket_type="AR", account_manager=pavan
    )

    with pytest.raises(HTTPException) as exc_info:
        await service.create_request(
            current_user=requester,
            request=PermissionRequestCreate(
                permission_id=scenario["permission_id"],
                reason="Trying to access a ticket outside my category.",
                scope_ticket_id=ticket.ticket_id,
            ),
        )

    assert exc_info.value.status_code == 400

    pending_rows = await PermissionRequestRepository(session).list_pending_by_scope_ticket(
        ticket.ticket_id
    )
    assert pending_rows == []


async def test_ticket_owner_can_approve_without_general_override_authority(scenario):
    """
    The reviewer of a ticket-scoped request is the ticket's own owner
    (here, Staff Pavan) — Pavan holds no general permission:override_
    grant authority and would 403 out of the ordinary Users > Permission
    Overrides admin flow, but approving a request addressed to him
    must still work: create_request/approve()'s own selected_approver_id
    check is already the right, narrower authorization for this one
    grant.
    """
    session, service = scenario["session"], scenario["service"]
    ram, pavan = scenario["ram"], scenario["pavan"]

    _, ticket = await _make_ticket(
        session, owner=pavan, ticket_type="AR", account_manager=pavan
    )

    response = await service.create_request(
        current_user=ram,
        request=PermissionRequestCreate(
            permission_id=scenario["permission_id"],
            reason="Need to update the ticket because I am handling this issue.",
            scope_ticket_id=ticket.ticket_id,
        ),
    )
    assert response.selected_approver_id == pavan.user_id

    approved = await service.approve(
        current_user=pavan,
        request_id=response.request_id,
        request=PermissionRequestApprove(),
    )

    assert approved.status == PermissionRequestStatus.APPROVED
    assert approved.granted_override_id is not None
