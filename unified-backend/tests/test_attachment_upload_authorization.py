# test_attachment_upload_authorization.py
#
# Regression coverage for a real reported bug: the person legitimately
# assigned to a ticket (ticket.agent_id == current_user.user_id) was
# rejected uploading an attachment with
# "Only the agent this ticket is assigned to can perform this action."
# — AttachmentService.upload_attachment's own authorization call
# (access_control.ensure_agent_can_act_on_ticket) is structurally
# correct and uses canonical UUID comparison
# (ticket.agent_id == current_user.user_id), never a role/display-name
# comparison — the actual root cause was a live-data gap: the Staff
# role's role_permissions grants in the connected (shared, dev) Neon
# database were missing ticket:editown_ticket entirely, even though
# scripts/rbac_seed/seed.py's DEFAULT_ROLES has always declared it as
# a Staff default. Since every other agent role (Team Lead, Account
# Manager, Site Lead, Super Admin) bypasses this whole check via
# SUPERVISOR_ROLE_NAMES, Staff was the only role that could ever
# actually reach — and therefore ever be wrongly rejected by — this
# specific branch. Fixed by re-running the additive-only, idempotent
# seed script against the connected database (no code change needed
# for that half — the bug was live-data drift, not a logic defect).
#
# A second, real, in-scope gap found in the same investigation:
# AttachmentService never accepted or threaded an edit_access_repository
# through to ensure_agent_can_act_on_ticket, unlike every one of
# InteractionService's own mutating actions (reply/internal-note/
# status-change) — a user holding an active, approved per-ticket
# edit-access grant could already act on those, but would still 403
# uploading an attachment specifically. Fixed by giving AttachmentService
# the same optional edit_access_repository parameter/threading those
# already have.
#
# A THIRD, more serious live-data bug was caught while live-verifying
# the first fix over the real HTTP API: the connected database's Staff
# role also held ticket:editother_ticket (which scripts/rbac_seed/
# seed.py's own DEFAULT_ROLES has never granted Staff — the whole point
# of the editown_ticket/editother_ticket split is that editother_ticket
# is Full for every role except Staff). Confirmed live with two real
# accounts: a Staff member with no relationship to a ticket at all (not
# the assignee, no scoped override, no edit-access grant) could still
# upload to it, because has_permission_for_ticket's unscoped
# has_permission check found editother_ticket sitting in their JWT's
# permissions claim. Fixed by adding ("Staff", "ticket:editother_ticket")
# to seed.py's REVOKED_GRANTS list (the existing, established mechanism
# for exactly this class of over-grant drift) and re-running the seed
# script.
#
# These tests exercise the real authorization logic directly (canonical
# UUID/permission checks), not a re-seed of the database — the two
# seed-data fixes above are operational/data steps, verified separately
# via a live API check (see the session's final report). One test below
# (test_staff_role_never_has_editother_ticket_permission_in_seed_data)
# does query the real connected database directly, specifically to
# guard against the third bug's exact shape recurring silently.
#
# Runs against the real (dev) database inside a transaction that is
# always rolled back at the end — same convention as
# test_ticket_attachments.py / test_transfer_agent_ownership.py.

import io
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import joinedload
from shared_models.models import Role, User

from app.database.session import AsyncSessionLocal, engine
from app.ticketing.enums import (
    EditAccessStatus,
    EscalationLevel,
    EscalationStatus,
    TicketPriority,
)
from app.ticketing.models.client import Client
from app.ticketing.models.ticket import Ticket
from app.ticketing.models.ticket_edit_access_request import TicketEditAccessRequest
from app.ticketing.models.ticket_escalation import TicketEscalation
from app.ticketing.repositories.attachment_repository import AttachmentRepository
from app.ticketing.repositories.client_repository import ClientRepository
from app.ticketing.repositories.escalation_handling_sla_repository import (
    EscalationHandlingSlaRepository,
)
from app.ticketing.repositories.interaction_repository import InteractionRepository
from app.ticketing.repositories.ticket_edit_access_repository import (
    TicketEditAccessRequestRepository,
)
from app.ticketing.repositories.ticket_escalation_repository import (
    TicketEscalationRepository,
)
from app.ticketing.repositories.ticket_repository import TicketRepository
from app.ticketing.repositories.user_repository import UserRepository
from app.ticketing.services.attachment_service import AttachmentService
from app.ticketing.storage.base import StorageService


class FakeStorageService(StorageService):
    """
    Minimal in-memory stand-in that actually performs the upload/read
    paths upload_attachment exercises (unlike test_ticket_attachments.py's
    read-only FakeStorageService, whose upload/delete raise) — these
    tests need a real round trip through validate_and_store_files.
    """

    bucket = "test-bucket"

    def __init__(self):
        self._objects: dict[str, bytes] = {}

    async def upload(self, *, data: bytes, object_key: str, content_type: str) -> None:
        self._objects[object_key] = data

    async def download(self, *, object_key: str) -> bytes:
        return self._objects[object_key]

    async def delete(self, *, object_key: str) -> None:
        self._objects.pop(object_key, None)

    async def exists(self, *, object_key: str) -> bool:
        return object_key in self._objects

    async def presigned_get_url(
        self, *, object_key: str, filename: str, inline: bool = False
    ) -> str:
        return f"https://fake-storage.test/{object_key}"


class FakeUploadFile:
    """
    A minimal stand-in for fastapi.UploadFile — upload_attachment only
    ever reads `.filename`, `.content_type`, and awaits `.read()`.
    """

    def __init__(self, filename: str, content: bytes, content_type: str):
        self.filename = filename
        self.content_type = content_type
        self._content = content

    async def read(self) -> bytes:
        return self._content


def _make_file(filename="test.pdf", content_type="application/pdf") -> FakeUploadFile:
    return FakeUploadFile(filename, b"%PDF-1.4 test content", content_type)


@pytest.fixture
async def db_session():
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.rollback()
    await engine.dispose()


async def _find_team_lead_with_staff(session, staff_count: int) -> tuple[User, list[User]]:
    team_lead_result = await session.execute(
        select(User)
        .options(joinedload(User.role), joinedload(User.category))
        .join(Role, Role.role_id == User.role_id)
        .where(Role.name == "Team Lead", User.is_active.is_(True))
    )
    team_leads = [
        user for user in team_lead_result.unique().scalars().all() if user.category is not None
    ]

    staff_result = await session.execute(
        select(User)
        .options(joinedload(User.role), joinedload(User.category))
        .join(Role, Role.role_id == User.role_id)
        .where(Role.name == "Staff", User.is_active.is_(True))
    )
    staff_by_category: dict[str, list[User]] = {}
    for user in staff_result.unique().scalars().all():
        if user.category is None:
            continue
        staff_by_category.setdefault(user.category.category_name.value, []).append(user)

    for team_lead in team_leads:
        candidates = staff_by_category.get(team_lead.category.category_name.value, [])
        if len(candidates) >= staff_count:
            return team_lead, candidates[:staff_count]

    pytest.skip(
        f"No category currently has both an active Team Lead and {staff_count} "
        "active Staff in the connected database."
    )


async def _make_ticket(session, *, account_manager_id, ticket_type, agent_id=None):
    client = Client(
        client_id=uuid.uuid4(),
        name="Attachment-Auth Test Client",
        inbox_email=f"attachment-auth-test-{uuid.uuid4().hex[:8]}@example.com",
        account_manager_id=account_manager_id,
        is_active=True,
    )
    session.add(client)
    await session.flush()

    ticket = Ticket(
        ticket_id=uuid.uuid4(),
        client_company_id=client.client_id,
        agent_id=agent_id,
        title="Attachment-authorization regression test ticket",
        ticket_type=ticket_type,
        current_status="IN_PROGRESS",
        current_priority=TicketPriority.MEDIUM,
        created_at=datetime.now(timezone.utc),
    )
    session.add(ticket)
    await session.flush()
    return client, ticket


def _build_service(session, *, with_edit_access=True) -> AttachmentService:
    return AttachmentService(
        attachment_repository=AttachmentRepository(session),
        interaction_repository=InteractionRepository(session),
        ticket_repository=TicketRepository(session),
        storage_service=FakeStorageService(),
        client_repository=ClientRepository(session),
        escalation_repository=TicketEscalationRepository(session),
        escalation_handling_sla_repository=EscalationHandlingSlaRepository(session),
        edit_access_repository=(
            TicketEditAccessRequestRepository(session) if with_edit_access else None
        ),
    )


# ---------------------------------------------------------------
# 1. The exact reported bug, fixed: the assigned Staff member, with
#    ticket:editown_ticket actually granted (the corrected, intended
#    state per seed.py's own DEFAULT_ROLES — see the reseed step in
#    this session's report), can upload to their own ticket.
# ---------------------------------------------------------------


async def test_assigned_staff_with_editown_ticket_permission_can_upload(db_session):
    team_lead, [staff] = await _find_team_lead_with_staff(db_session, 1)
    staff.permissions = ["ticket:editown_ticket", "ticket:upload_attachment"]
    _client, ticket = await _make_ticket(
        db_session,
        account_manager_id=team_lead.manager_id or team_lead.user_id,
        ticket_type=team_lead.category.category_name.value,
        agent_id=staff.user_id,
    )

    service = _build_service(db_session)
    response = await service.upload_attachment(
        ticket_id=ticket.ticket_id,
        files=[_make_file()],
        current_user=staff,
    )

    assert len(response.attachments) == 1
    assert response.attachments[0].filename == "test.pdf"


# ---------------------------------------------------------------
# 2. The exact mechanism of the bug, reproduced directly: an assigned
#    Staff member whose token/permissions claim does NOT include
#    ticket:editown_ticket (the live-data-drift scenario this bug
#    actually came from) is still correctly rejected — proving the
#    fix is the permission grant itself, not a code-side bypass. This
#    must keep failing even after the fix, since granting nobody a
#    blanket ownership bypass is the whole point of the permission
#    check.
# ---------------------------------------------------------------


async def test_assigned_staff_without_editown_ticket_permission_is_rejected(db_session):
    team_lead, [staff] = await _find_team_lead_with_staff(db_session, 1)
    staff.permissions = ["ticket:upload_attachment"]  # editown_ticket deliberately absent
    _client, ticket = await _make_ticket(
        db_session,
        account_manager_id=team_lead.manager_id or team_lead.user_id,
        ticket_type=team_lead.category.category_name.value,
        agent_id=staff.user_id,
    )

    service = _build_service(db_session)
    with pytest.raises(HTTPException) as exc_info:
        await service.upload_attachment(
            ticket_id=ticket.ticket_id,
            files=[_make_file()],
            current_user=staff,
        )
    assert exc_info.value.status_code == 403
    assert "Only the agent this ticket is assigned to" in exc_info.value.detail


# ---------------------------------------------------------------
# 3. A non-assigned Staff member (different agent_id), with neither
#    ticket:editother_ticket nor an edit-access grant, is still
#    rejected — this must NOT regress: the fix must never widen who
#    can upload beyond the actual assignee/permission holder.
# ---------------------------------------------------------------


async def test_non_assigned_staff_without_permission_or_grant_is_rejected(db_session):
    team_lead, [staff_a, staff_b] = await _find_team_lead_with_staff(db_session, 2)
    staff_b.permissions = ["ticket:upload_attachment"]
    _client, ticket = await _make_ticket(
        db_session,
        account_manager_id=team_lead.manager_id or team_lead.user_id,
        ticket_type=team_lead.category.category_name.value,
        agent_id=staff_a.user_id,
    )

    service = _build_service(db_session)
    with pytest.raises(HTTPException) as exc_info:
        await service.upload_attachment(
            ticket_id=ticket.ticket_id,
            files=[_make_file()],
            current_user=staff_b,
        )
    assert exc_info.value.status_code == 403


# ---------------------------------------------------------------
# 4. Supervisor-tier roles (Team Lead/Account Manager/Site Lead/Super
#    Admin) can always upload regardless of assignment — the
#    SUPERVISOR_ROLE_NAMES bypass, unaffected by this fix, still
#    applies. This is also why the reported bug could only ever
#    manifest for Staff: every other role bypasses the ownership
#    check entirely.
# ---------------------------------------------------------------


async def test_team_lead_can_upload_to_unassigned_or_other_agents_ticket(db_session):
    team_lead, [staff] = await _find_team_lead_with_staff(db_session, 1)
    team_lead.permissions = ["ticket:upload_attachment"]
    _client, ticket = await _make_ticket(
        db_session,
        account_manager_id=team_lead.manager_id or team_lead.user_id,
        ticket_type=team_lead.category.category_name.value,
        agent_id=staff.user_id,
    )

    service = _build_service(db_session)
    response = await service.upload_attachment(
        ticket_id=ticket.ticket_id,
        files=[_make_file(filename="supervisor-upload.pdf")],
        current_user=team_lead,
    )
    assert len(response.attachments) == 1


# ---------------------------------------------------------------
# 5. The NEW fix: a non-assigned Staff member with an active,
#    approved, per-ticket edit-access grant can now upload — matching
#    every other InteractionService mutating action's existing
#    edit-access bypass, which AttachmentService never had before this
#    session.
# ---------------------------------------------------------------


async def test_non_assigned_staff_with_active_edit_access_grant_can_upload(db_session):
    team_lead, [staff_a, staff_b] = await _find_team_lead_with_staff(db_session, 2)
    staff_b.permissions = ["ticket:upload_attachment"]
    _client, ticket = await _make_ticket(
        db_session,
        account_manager_id=team_lead.manager_id or team_lead.user_id,
        ticket_type=team_lead.category.category_name.value,
        agent_id=staff_a.user_id,
    )

    grant = TicketEditAccessRequest(
        request_id=uuid.uuid4(),
        ticket_id=ticket.ticket_id,
        requested_by=staff_b.user_id,
        reason="Covering for staff_a while out of office",
        status=EditAccessStatus.APPROVED,
        reviewed_by=team_lead.user_id,
        reviewed_at=datetime.now(timezone.utc),
        expires_at=datetime.now(timezone.utc) + timedelta(days=1),
    )
    db_session.add(grant)
    await db_session.flush()

    service = _build_service(db_session)
    response = await service.upload_attachment(
        ticket_id=ticket.ticket_id,
        files=[_make_file(filename="edit-access-upload.pdf")],
        current_user=staff_b,
    )
    assert len(response.attachments) == 1


# ---------------------------------------------------------------
# 6. Backward compatibility: a caller that constructs AttachmentService
#    without edit_access_repository (the pre-fix shape) must keep
#    degrading safely to "skip that bypass", not crash — same
#    optional-parameter convention as escalation_repository/
#    escalation_handling_sla_repository already use.
# ---------------------------------------------------------------


async def test_edit_access_grant_is_ignored_when_repository_not_supplied(db_session):
    team_lead, [staff_a, staff_b] = await _find_team_lead_with_staff(db_session, 2)
    staff_b.permissions = ["ticket:upload_attachment"]
    _client, ticket = await _make_ticket(
        db_session,
        account_manager_id=team_lead.manager_id or team_lead.user_id,
        ticket_type=team_lead.category.category_name.value,
        agent_id=staff_a.user_id,
    )

    grant = TicketEditAccessRequest(
        request_id=uuid.uuid4(),
        ticket_id=ticket.ticket_id,
        requested_by=staff_b.user_id,
        reason="Covering for staff_a while out of office",
        status=EditAccessStatus.APPROVED,
        reviewed_by=team_lead.user_id,
        reviewed_at=datetime.now(timezone.utc),
        expires_at=None,
    )
    db_session.add(grant)
    await db_session.flush()

    service = _build_service(db_session, with_edit_access=False)
    with pytest.raises(HTTPException) as exc_info:
        await service.upload_attachment(
            ticket_id=ticket.ticket_id,
            files=[_make_file()],
            current_user=staff_b,
        )
    assert exc_info.value.status_code == 403


# ---------------------------------------------------------------
# 7. A closed ticket still blocks upload for everyone, including the
#    assigned agent — ensure_ticket_not_closed is unaffected by this
#    fix.
# ---------------------------------------------------------------


async def test_closed_ticket_blocks_upload_even_for_assigned_agent(db_session):
    team_lead, [staff] = await _find_team_lead_with_staff(db_session, 1)
    staff.permissions = ["ticket:editown_ticket", "ticket:upload_attachment"]
    _client, ticket = await _make_ticket(
        db_session,
        account_manager_id=team_lead.manager_id or team_lead.user_id,
        ticket_type=team_lead.category.category_name.value,
        agent_id=staff.user_id,
    )
    ticket.current_status = "CLOSED"
    await db_session.flush()

    service = _build_service(db_session)
    with pytest.raises(HTTPException) as exc_info:
        await service.upload_attachment(
            ticket_id=ticket.ticket_id,
            files=[_make_file()],
            current_user=staff,
        )
    assert exc_info.value.status_code == 400


# ---------------------------------------------------------------
# 8. An escalated ticket awaiting acceptance freezes upload for
#    *everyone*, including the assigned agent and supervisors alike —
#    ensure_ticket_not_frozen_by_escalation is unaffected by this fix,
#    and this is the one case that must reject even a supervisor.
# ---------------------------------------------------------------


async def test_escalated_ticket_awaiting_acceptance_blocks_upload_for_everyone(db_session):
    team_lead, [staff] = await _find_team_lead_with_staff(db_session, 1)
    staff.permissions = ["ticket:editown_ticket", "ticket:upload_attachment"]
    team_lead.permissions = ["ticket:upload_attachment"]
    _client, ticket = await _make_ticket(
        db_session,
        account_manager_id=team_lead.manager_id or team_lead.user_id,
        ticket_type=team_lead.category.category_name.value,
        agent_id=staff.user_id,
    )

    escalation = TicketEscalation(
        escalation_id=uuid.uuid4(),
        ticket_id=ticket.ticket_id,
        level=EscalationLevel.TEAM_LEAD,
        status=EscalationStatus.ACTIVE,
        owner_ids=[str(team_lead.user_id)],
        original_priority=TicketPriority.MEDIUM,
        triggered_by="MANUAL",
        ack_due_at=datetime.now(timezone.utc) + timedelta(minutes=10),
        created_at=datetime.now(timezone.utc),
    )
    db_session.add(escalation)
    await db_session.flush()

    service = _build_service(db_session)

    with pytest.raises(HTTPException) as exc_info:
        await service.upload_attachment(
            ticket_id=ticket.ticket_id,
            files=[_make_file()],
            current_user=staff,
        )
    assert exc_info.value.status_code == 403
    assert "escalated" in exc_info.value.detail.lower()

    with pytest.raises(HTTPException) as exc_info_supervisor:
        await service.upload_attachment(
            ticket_id=ticket.ticket_id,
            files=[_make_file()],
            current_user=team_lead,
        )
    assert exc_info_supervisor.value.status_code == 403


# ---------------------------------------------------------------
# 9. Persistence and visibility: a successfully uploaded attachment
#    actually persists and is visible via the same
#    InteractionService.get_ticket_attachments path the Attachments
#    tab reads from — not just a 200 response with no real row behind
#    it.
# ---------------------------------------------------------------


async def test_uploaded_attachment_persists_and_is_visible_afterward(db_session):
    from app.ticketing.services.interaction_service import InteractionService

    team_lead, [staff] = await _find_team_lead_with_staff(db_session, 1)
    staff.permissions = ["ticket:editown_ticket", "ticket:upload_attachment"]
    _client, ticket = await _make_ticket(
        db_session,
        account_manager_id=team_lead.manager_id or team_lead.user_id,
        ticket_type=team_lead.category.category_name.value,
        agent_id=staff.user_id,
    )

    attachment_service = _build_service(db_session)
    response = await attachment_service.upload_attachment(
        ticket_id=ticket.ticket_id,
        files=[_make_file(filename="persisted.pdf")],
        current_user=staff,
    )
    assert len(response.attachments) == 1

    view_service = InteractionService(
        interaction_repository=InteractionRepository(db_session),
        ticket_repository=TicketRepository(db_session),
        user_repository=UserRepository(db_session),
        client_repository=ClientRepository(db_session),
        attachment_repository=AttachmentRepository(db_session),
        storage_service=FakeStorageService(),
    )
    rows = await view_service.get_ticket_attachments(ticket.ticket_id, team_lead)
    assert len(rows) == 1
    assert rows[0].filename == "persisted.pdf"


# ---------------------------------------------------------------
# 10. A direct guard against the third live-data bug found this
#     session recurring silently: the Staff role must never hold
#     ticket:editother_ticket in the connected database's own
#     role_permissions table — scripts/rbac_seed/seed.py's DEFAULT_ROLES
#     has never granted it to Staff (see this file's own header
#     comment), and its presence is what let a completely unrelated
#     Staff member upload to (and, by the same code path, reply/change
#     status on) any other Staff member's ticket. Unlike every other
#     test in this file, this one queries the real database directly
#     rather than simulating a JWT's permissions list, since the bug
#     it guards against is a data-drift issue no amount of correct
#     application code can catch on its own.
# ---------------------------------------------------------------


async def test_staff_role_never_has_editother_ticket_permission_in_seed_data(db_session):
    result = await db_session.execute(
        select(User)
        .join(Role, Role.role_id == User.role_id)
        .where(Role.name == "Staff")
        .limit(1)
    )
    if result.scalars().first() is None:
        pytest.skip("No Staff role exists in the connected database.")

    from sqlalchemy import text

    row = await db_session.execute(
        text(
            """
            SELECT 1
            FROM role_permissions rp
            JOIN roles r ON r.role_id = rp.role_id
            JOIN permissions p ON p.permission_id = rp.permission_id
            WHERE r.name = 'Staff' AND p.permission_name = 'ticket:editother_ticket'
            """
        )
    )
    assert row.first() is None, (
        "Staff must never hold ticket:editother_ticket — this permission "
        "lets its holder act on ANY ticket regardless of assignment, "
        "which is exactly the over-grant bug this test guards against. "
        "If this fails, re-run scripts/rbac_seed/seed.py (REVOKED_GRANTS "
        "now includes this entry) against the connected database."
    )
