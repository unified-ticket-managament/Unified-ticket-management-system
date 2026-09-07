# test_audit_export_permission.py
#
# Phase 50 (audit:export becomes a real, permission-controlled export
# feature): GET /audit-logs/export previously did not exist at all —
# the frontend's Export button generated a CSV purely client-side from
# whatever rows were already loaded in the browser, with no backend
# authorization of any kind. This file covers the new route
# (export_audit_logs, unified-backend/app/rbac/api/v1/audit_logs.py).
#
# The route requires BOTH audit:view AND audit:export — not
# audit:export alone — specifically because personal permission
# overrides (PermissionOverrideService.grant) have no cross-permission
# validation, so a user could in principle hold audit:export without
# audit:view via an individual override. Requiring both closes that
# gap: this route can never become a second way to see audit data that
# audit:view itself wouldn't already allow.
#
# Same convention as test_audit_log_list_permission.py: route function
# called directly, real seeded users, `.permissions` set explicitly per
# test, everything inside a transaction that is always rolled back. Run
# this file individually (DB-touching test caveat, see root CLAUDE.md).

import csv
import io
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import joinedload
from shared_models.models import Role, User

from app.database.session import AsyncSessionLocal, engine
from app.rbac.api.v1.audit_logs import export_audit_logs
from app.rbac.models.audit_log import AuditLog
from app.rbac.repositories.audit_log_repository import AuditLogRepository
from app.rbac.repositories.role_repository import RoleRepository
from app.rbac.services.audit_log_service import AuditLogService


@pytest.fixture
async def db_session():
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.rollback()
    await engine.dispose()


def _build_service(session) -> AuditLogService:
    return AuditLogService(audit_log_repository=AuditLogRepository(session))


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


async def _read_csv(response: StreamingResponse) -> list[list[str]]:
    assert isinstance(response, StreamingResponse)
    body_parts = [part async for part in response.body_iterator]
    body = "".join(
        part.decode("utf-8") if isinstance(part, (bytes, bytearray)) else part
        for part in body_parts
    )
    return list(csv.reader(io.StringIO(body)))


# ---------------------------------------------------------
# Authorization matrix — the core of this phase's requirement.
# ---------------------------------------------------------


async def test_actor_with_both_permissions_can_export(db_session):
    service = _build_service(db_session)
    actor = await _get_user_by_role(db_session, "Super Admin")
    actor.permissions = ["audit:view", "audit:export"]

    response = await export_audit_logs(
        search=None, date_from=None, date_to=None, service=service, current_user=actor
    )
    assert isinstance(response, StreamingResponse)
    assert response.media_type == "text/csv"
    assert "attachment" in response.headers["Content-Disposition"]


async def test_actor_with_export_only_no_view_is_denied(db_session):
    """The specific override-bypass risk this phase's design guards
    against: audit:export alone must never be sufficient."""

    service = _build_service(db_session)
    actor = await _get_user_by_role(db_session, "Staff")
    actor.permissions = ["audit:export"]  # simulates an override granting export w/o view

    with pytest.raises(HTTPException) as exc_info:
        await export_audit_logs(
            search=None, date_from=None, date_to=None, service=service, current_user=actor
        )
    assert exc_info.value.status_code == 403


async def test_actor_with_view_only_no_export_is_denied(db_session):
    """audit:view alone (e.g. Site Lead's real default grant, which
    deliberately excludes audit:export — see seed.py's
    _SITE_LEAD_EXCLUDED) must not be sufficient either."""

    service = _build_service(db_session)
    actor = await _get_user_by_role(db_session, "Site Lead")
    actor.permissions = ["audit:view"]

    with pytest.raises(HTTPException) as exc_info:
        await export_audit_logs(
            search=None, date_from=None, date_to=None, service=service, current_user=actor
        )
    assert exc_info.value.status_code == 403


async def test_actor_with_neither_permission_is_denied(db_session):
    service = _build_service(db_session)
    actor = await _get_user_by_role(db_session, "Team Lead")
    actor.permissions = []

    with pytest.raises(HTTPException) as exc_info:
        await export_audit_logs(
            search=None, date_from=None, date_to=None, service=service, current_user=actor
        )
    assert exc_info.value.status_code == 403


async def test_seed_py_source_excludes_site_lead_from_export(db_session):
    """Regression against this phase's own change only: confirms
    seed.py's source code still excludes audit:export from Site Lead
    (via _SITE_LEAD_EXCLUDED) — i.e. this phase did not edit seed.py or
    widen that exclusion list.

    Deliberately checks seed.py's DEFAULT_ROLES/exclusion source, NOT
    the live database's current role_permissions rows: a live query
    was found, independently of this phase's changes, to already grant
    Site Lead audit:export in this dev database — a pre-existing
    drift between an earlier phase's seed.py edit and this DB never
    having been re-seeded since (see this phase's own final report).
    Asserting against the live DB here would make this test either
    fail on that unrelated, pre-existing drift, or silently launder it
    as "passing" — neither is this test's job. export_audit_logs
    itself correctly enforces whatever is actually granted at request
    time either way (see the .permissions-based tests above), so that
    behavior doesn't depend on which of the two states is checked here.
    """

    from scripts.rbac_seed.seed import DEFAULT_ROLES, _SITE_LEAD_EXCLUDED

    assert "audit:export" in _SITE_LEAD_EXCLUDED
    site_lead_defaults = DEFAULT_ROLES.get("Site Lead", [])
    assert "audit:export" not in site_lead_defaults


async def test_staff_granted_both_via_override_can_export(db_session):
    """Proves this is a real permission check, not a role check in
    disguise: Staff (holds neither by default) succeeds once both are
    explicitly granted, mirroring the established
    test_actor_granted_audit_view_via_override_can_list pattern."""

    service = _build_service(db_session)
    actor = await _get_user_by_role(db_session, "Staff")
    actor.permissions = ["audit:view", "audit:export"]

    response = await export_audit_logs(
        search=None, date_from=None, date_to=None, service=service, current_user=actor
    )
    assert isinstance(response, StreamingResponse)


# ---------------------------------------------------------
# Data correctness — export must reuse the same unscoped data
# list_audit_logs already exposes, never a separate visibility model.
# ---------------------------------------------------------


async def test_export_csv_has_expected_header_and_status_column(db_session):
    service = _build_service(db_session)
    actor = await _get_user_by_role(db_session, "Super Admin")
    actor.permissions = ["audit:view", "audit:export"]

    marker = f"phase50_export_test_{uuid.uuid4().hex[:8]}"
    base_time = datetime.now(timezone.utc)
    db_session.add_all(
        [
            AuditLog(
                audit_log_id=uuid.uuid4(),
                user_id=None,
                action=f"{marker}.login_failed",
                entity_type="auth",
                entity_id="1",
                timestamp=base_time,
            ),
            AuditLog(
                audit_log_id=uuid.uuid4(),
                user_id=None,
                action=f"{marker}.user.create",
                entity_type="user",
                entity_id="2",
                timestamp=base_time,
            ),
        ]
    )
    await db_session.flush()

    response = await export_audit_logs(
        search=marker, date_from=None, date_to=None, service=service, current_user=actor
    )
    rows = await _read_csv(response)

    assert rows[0] == [
        "User", "Email", "Role", "Action", "Entity", "Entity ID", "Status", "Timestamp", "IP Address",
    ]
    data_rows = rows[1:]
    assert len(data_rows) == 2

    by_action = {row[3]: row for row in data_rows}
    assert by_action[f"{marker}.login_failed"][6] == "Failed"
    assert by_action[f"{marker}.user.create"][6] == "Success"


async def test_export_search_filters_like_the_frontend_does(db_session):
    service = _build_service(db_session)
    actor = await _get_user_by_role(db_session, "Super Admin")
    actor.permissions = ["audit:view", "audit:export"]

    marker = f"phase50_search_test_{uuid.uuid4().hex[:8]}"
    db_session.add(
        AuditLog(
            audit_log_id=uuid.uuid4(),
            user_id=None,
            action=marker,
            entity_type="test",
            entity_id="1",
            timestamp=datetime.now(timezone.utc),
        )
    )
    await db_session.flush()

    matching = await export_audit_logs(
        search=marker, date_from=None, date_to=None, service=service, current_user=actor
    )
    matching_rows = await _read_csv(matching)
    assert len(matching_rows) == 2  # header + 1

    non_matching = await export_audit_logs(
        search=f"{marker}_does_not_exist",
        date_from=None,
        date_to=None,
        service=service,
        current_user=actor,
    )
    non_matching_rows = await _read_csv(non_matching)
    assert len(non_matching_rows) == 1  # header only


async def test_export_date_range_filters(db_session):
    service = _build_service(db_session)
    actor = await _get_user_by_role(db_session, "Super Admin")
    actor.permissions = ["audit:view", "audit:export"]

    marker = f"phase50_daterange_test_{uuid.uuid4().hex[:8]}"
    now = datetime.now(timezone.utc)
    db_session.add(
        AuditLog(
            audit_log_id=uuid.uuid4(),
            user_id=None,
            action=marker,
            entity_type="test",
            entity_id="1",
            timestamp=now,
        )
    )
    await db_session.flush()

    today = now.date().isoformat()
    yesterday = (now - timedelta(days=1)).date().isoformat()
    tomorrow = (now + timedelta(days=1)).date().isoformat()

    in_range = await export_audit_logs(
        search=marker, date_from=yesterday, date_to=tomorrow, service=service, current_user=actor
    )
    assert len(await _read_csv(in_range)) == 2

    out_of_range = await export_audit_logs(
        search=marker, date_from=tomorrow, date_to=None, service=service, current_user=actor
    )
    assert len(await _read_csv(out_of_range)) == 1

    exact_day = await export_audit_logs(
        search=marker, date_from=today, date_to=today, service=service, current_user=actor
    )
    assert len(await _read_csv(exact_day)) == 2


async def test_export_invalid_date_format_is_rejected(db_session):
    service = _build_service(db_session)
    actor = await _get_user_by_role(db_session, "Super Admin")
    actor.permissions = ["audit:view", "audit:export"]

    with pytest.raises(HTTPException) as exc_info:
        await export_audit_logs(
            search=None,
            date_from="not-a-date",
            date_to=None,
            service=service,
            current_user=actor,
        )
    assert exc_info.value.status_code == 400


# ---------------------------------------------------------
# Regression: the pre-existing list/get/user-log routes on this same
# router are unaffected by adding export_audit_logs.
# ---------------------------------------------------------


async def test_sibling_routes_still_unaffected(db_session):
    from app.rbac.api.v1.audit_logs import get_audit_log, list_audit_logs

    service = _build_service(db_session)
    actor = await _get_user_by_role(db_session, "Super Admin")
    actor.permissions = ["audit:view"]  # deliberately NOT audit:export

    # list/get only ever required audit:view — must still work without
    # audit:export, proving export's stricter gate didn't leak onto them.
    result = await list_audit_logs(page=1, page_size=5, service=service, current_user=actor)
    assert result.total >= 0

    with pytest.raises(HTTPException) as exc_info:
        await get_audit_log(uuid.uuid4(), service=service, current_user=actor)
    assert exc_info.value.status_code == 404  # reached the audit:view check fine, just no such id
