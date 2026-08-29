# test_audit_view_vs_global_audit_log_separation.py
#
# Regression coverage for the audit-log navigation unification: the
# Centralized/system-wide Audit Log (RBAC's own `audit_logs` table,
# GET /api/v1/audit-logs*) is gated by `audit:view`; the ticket-domain
# Audit Log's centralized-across-clients mode (`ticket_audit_logs`,
# GET /tickets/audit-logs?centralized=true) is gated independently by
# `ticket:view_global_audit_log`. Investigation found both gates were
# already correct before this change — this file proves they stay that
# way and, critically, that holding one permission never implies the
# other. See root CLAUDE.md's audit-log separation section and the
# approved plan (plan-separate-centralised-floating-liskov.md) for the
# full Case A-E matrix this file's tests are named after.
#
# Same convention as test_audit_log_list_permission.py /
# test_permission_catalog_authorization.py: route/service functions
# called directly, real seeded users, `.permissions` set explicitly
# per test, everything inside a transaction that is always rolled
# back. Run this file individually (DB-touching test caveat).

import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import joinedload
from shared_models.models import Role, User

from app.database.session import AsyncSessionLocal, engine
from app.rbac.api.v1.audit_logs import list_audit_logs
from app.rbac.repositories.audit_log_repository import AuditLogRepository as RbacAuditLogRepository
from app.rbac.repositories.role_permission_repository import RolePermissionRepository
from app.rbac.repositories.role_repository import RoleRepository
from app.rbac.services.audit_log_service import AuditLogService as RbacAuditLogService
from app.ticketing.api import mail_integration as mail_integration_module
from app.ticketing.enums import TicketPriority
from app.ticketing.repositories.audit_log_repository import (
    AuditLogRepository as TicketingAuditLogRepository,
)
from app.ticketing.repositories.client_repository import ClientRepository
from app.ticketing.repositories.sla_policy_repository import SLAPolicyRepository
from app.ticketing.repositories.ticket_repository import TicketRepository
from app.ticketing.repositories.user_repository import UserRepository as TicketingUserRepository
from app.ticketing.schemas.sla import SLAPolicyUpdate
from app.ticketing.services.sla_service import build_sla_service
from app.ticketing.services.ticket_service import TicketService


@pytest.fixture
async def db_session():
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.rollback()
    await engine.dispose()


def _build_rbac_audit_service(session) -> RbacAuditLogService:
    return RbacAuditLogService(audit_log_repository=RbacAuditLogRepository(session))


def _build_ticket_service(session) -> TicketService:
    return TicketService(
        ticket_repository=TicketRepository(session),
        user_repository=TicketingUserRepository(session),
        client_repository=ClientRepository(session),
        audit_log_repository=TicketingAuditLogRepository(session),
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


async def _get_role(session, role_name: str) -> Role:
    role = await RoleRepository(session).get_by_name(role_name)
    if role is None:
        pytest.skip(f"No {role_name!r} role seeded.")
    return role


# ---------------------------------------------------------
# Case A: audit:view alone -> Centralized (RBAC) Audit Log accessible;
# ticket-domain centralized mode is NOT (proven together, since this
# is the actual "the two permissions are independent" claim).
# ---------------------------------------------------------


async def test_case_a_audit_view_alone_grants_centralized_rbac_access(db_session):
    service = _build_rbac_audit_service(db_session)
    actor = await _get_user_by_role(db_session, "Account Manager")
    actor.permissions = ["audit:view"]

    result = await list_audit_logs(page=1, page_size=20, service=service, current_user=actor)
    assert result.total >= 0


async def test_case_a_audit_view_alone_does_not_grant_ticket_centralized(db_session):
    """The core independence proof: holding audit:view must never
    satisfy ticket:view_global_audit_log's own gate."""

    ticket_service = _build_ticket_service(db_session)
    actor = await _get_user_by_role(db_session, "Account Manager")
    actor.permissions = ["audit:view"]

    with pytest.raises(HTTPException) as exc_info:
        await ticket_service.list_all_audit_logs(
            actor, limit=1, offset=0, centralized=True
        )
    assert exc_info.value.status_code == 403


# ---------------------------------------------------------
# Case B: ticket:view_global_audit_log alone -> ticket-domain
# centralized mode accessible; Centralized (RBAC) Audit Log is NOT.
# ---------------------------------------------------------


async def test_case_b_ticket_view_global_audit_log_alone_grants_ticket_centralized(db_session):
    ticket_service = _build_ticket_service(db_session)
    actor = await _get_user_by_role(db_session, "Account Manager")
    actor.permissions = ["ticket:view_global_audit_log"]

    responses, total = await ticket_service.list_all_audit_logs(
        actor, limit=1, offset=0, centralized=True
    )
    assert total >= 0


async def test_case_b_ticket_view_global_audit_log_alone_denies_rbac_audit_view(db_session):
    """The other half of the independence proof: holding
    ticket:view_global_audit_log must never satisfy audit:view's own
    gate — this is the exact confusion the original request described."""

    service = _build_rbac_audit_service(db_session)
    actor = await _get_user_by_role(db_session, "Account Manager")
    actor.permissions = ["ticket:view_global_audit_log"]

    with pytest.raises(HTTPException) as exc_info:
        await list_audit_logs(page=1, page_size=20, service=service, current_user=actor)
    assert exc_info.value.status_code == 403


# ---------------------------------------------------------
# Case C: both permissions -> both views accessible, independently.
# ---------------------------------------------------------


async def test_case_c_both_permissions_grant_both_views(db_session):
    service = _build_rbac_audit_service(db_session)
    ticket_service = _build_ticket_service(db_session)
    actor = await _get_user_by_role(db_session, "Team Lead")
    actor.permissions = ["audit:view", "ticket:view_global_audit_log"]

    rbac_result = await list_audit_logs(page=1, page_size=20, service=service, current_user=actor)
    assert rbac_result.total >= 0

    _, ticket_total = await ticket_service.list_all_audit_logs(
        actor, limit=1, offset=0, centralized=True
    )
    assert ticket_total >= 0


# ---------------------------------------------------------
# Case D: neither permission -> both views denied. The normal,
# unbounded (non-centralized) ticket-scoped view is untouched by
# either permission and still works — proven separately in
# test_audit_log_list_permission.py / the ticket-workspace's own
# existing scoped-view tests, not re-derived here.
# ---------------------------------------------------------


async def test_case_d_neither_permission_denies_both(db_session):
    service = _build_rbac_audit_service(db_session)
    ticket_service = _build_ticket_service(db_session)
    actor = await _get_user_by_role(db_session, "Account Manager")
    actor.permissions = []

    with pytest.raises(HTTPException) as exc_info:
        await list_audit_logs(page=1, page_size=20, service=service, current_user=actor)
    assert exc_info.value.status_code == 403

    with pytest.raises(HTTPException) as exc_info:
        await ticket_service.list_all_audit_logs(actor, limit=1, offset=0, centralized=True)
    assert exc_info.value.status_code == 403


# ---------------------------------------------------------
# Case E: Site Lead/Super Admin — permission-driven, not role-name
# hardcoded. Both already hold audit:view by default (seed.py); both
# bypass ticket:view_global_audit_log entirely for the ticket-domain
# centralized view via the existing, untouched GLOBAL_INBOX_ROLE_NAMES
# unrestricted-by-default behavior.
# ---------------------------------------------------------


@pytest.mark.parametrize("role_name", ["Super Admin", "Site Lead"])
async def test_case_e_supervisor_roles_hold_audit_view_by_default(db_session, role_name):
    role = await _get_role(db_session, role_name)
    names = {
        p.permission_name
        for p in await RolePermissionRepository(db_session).get_permissions_by_role(role.role_id)
    }
    assert "audit:view" in names


@pytest.mark.parametrize("role_name", ["Super Admin", "Site Lead"])
async def test_case_e_supervisor_roles_get_unrestricted_ticket_centralized_without_the_permission(
    db_session, role_name
):
    """Site Lead/Super Admin never need ticket:view_global_audit_log
    at all for their own default (GLOBAL_INBOX_ROLE_NAMES) unrestricted
    ticket-domain view — proven with permissions explicitly emptied so
    this can't be mistaken for a permission-driven pass."""

    ticket_service = _build_ticket_service(db_session)
    actor = await _get_user_by_role(db_session, role_name)
    actor.permissions = []

    _, total = await ticket_service.list_all_audit_logs(
        actor, limit=1, offset=0, centralized=True
    )
    assert total >= 0


# ---------------------------------------------------------
# Regression: mail_integration.list_inbound_mail_failures still
# authorizes off ticket:view_global_audit_log alone (unrelated to
# audit-log viewing, but reuses the same permission) — confirms this
# plan didn't touch its other consumer.
# ---------------------------------------------------------


async def test_mail_integration_global_audit_permission_unaffected(db_session):
    actor_denied = await _get_user_by_role(db_session, "Account Manager")
    actor_denied.permissions = []

    with pytest.raises(HTTPException) as exc_info:
        await mail_integration_module.list_inbound_mail_failures(
            limit=50, offset=0, current_user=actor_denied, db=db_session
        )
    assert exc_info.value.status_code == 403

    actor_allowed = await _get_user_by_role(db_session, "Account Manager")
    actor_allowed.permissions = ["ticket:view_global_audit_log"]

    response = await mail_integration_module.list_inbound_mail_failures(
        limit=50, offset=0, current_user=actor_allowed, db=db_session
    )
    assert response.total >= 0


# ---------------------------------------------------------
# Gap-coverage retrievability proof (Part 0 / Part 3, gap #9): a
# non-ticket-scoped SLA Policy edit is deliberately logged into RBAC's
# own audit_logs table (not ticket_audit_logs, where it would be
# permanently unreachable — see AuditLogRepository.list_visible_page's
# ticket_id IS NOT NULL requirement). This proves the resulting row is
# actually retrievable via list_audit_logs, not just written.
# ---------------------------------------------------------


async def test_sla_policy_update_is_logged_and_retrievable_via_centralized_audit(db_session):
    sla_service = build_sla_service(db_session)
    policy_repo = SLAPolicyRepository(db_session)

    policy = await policy_repo.get_by_priority(TicketPriority.MEDIUM)
    if policy is None:
        pytest.skip("No MEDIUM SLAPolicy row seeded.")

    actor = await _get_user_by_role(db_session, "Site Lead")
    actor.permissions = ["sla:manage_policies", "audit:view"]

    marker_minutes = 999
    await sla_service.update_policy(
        policy.policy_id,
        SLAPolicyUpdate(escalation_ack_target_minutes=marker_minutes),
        actor,
    )

    rbac_audit_service = _build_rbac_audit_service(db_session)
    result = await list_audit_logs(
        page=1, page_size=50, service=rbac_audit_service, current_user=actor
    )
    matching = [
        log
        for log in result.logs
        if log.action == "sla_policy.update" and log.entity_id == str(policy.policy_id)
    ]
    assert matching, "sla_policy.update row was written but not retrievable via GET /audit-logs"
