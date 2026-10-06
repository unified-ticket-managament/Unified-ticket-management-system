# test_multi_assignment_api_e2e.py
#
# End-to-end over HTTP: the real FastAPI app (every router, dependency,
# schema and service) driven through httpx's ASGI transport, with
# get_db pointed at one test session that is always rolled back and the
# auth dependency returning whichever user the test is "acting as"
# (with explicit RBAC permissions, exactly what the JWT would carry).
#
# Exercises full business flows across both the NEW assignment endpoints
# and the EXISTING ticket endpoints, so a regression in either surface —
# or in how they interact — fails here.

import uuid

import httpx
import pytest
from sqlalchemy import select

from app.database.session import AsyncSessionLocal, engine, get_db
from app.dependencies.auth import get_current_agent, get_current_user
from app.main import app
from app.ticketing.enums import AuditEventType
from app.ticketing.models.audit_log import AuditLog
from tests.multi_assignment_support import build_world, make_ticket


@pytest.fixture(autouse=True)
def _no_real_emails(monkeypatch):
    monkeypatch.setattr(
        "app.notifications.email_notifier.queue_notification_emails", lambda created: None
    )


@pytest.fixture
async def db_session():
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.rollback()
    await engine.dispose()


@pytest.fixture
async def world(db_session):
    return await build_world(db_session)


class Api:
    """Thin client: `as_(user)` switches the authenticated identity."""

    def __init__(self, client: httpx.AsyncClient, acting: dict):
        self.client = client
        self.acting = acting

    def as_(self, user):
        self.acting["user"] = user
        return self.client


@pytest.fixture
async def api(world):
    acting: dict = {"user": None}

    async def _forbid_commit():
        raise AssertionError("Test session must never commit to the shared database.")

    world.session.commit = _forbid_commit

    async def _db():
        yield world.session  # never committed — the fixture rolls it back

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[get_current_agent] = lambda: acting["user"]
    app.dependency_overrides[get_current_user] = lambda: acting["user"]
    transport = httpx.ASGITransport(app=app)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            yield Api(client, acting)
    finally:
        app.dependency_overrides.clear()


def by_user(body) -> dict:
    return {a["user_name"]: a for a in body["assignments"]}


async def test_full_multi_assignment_lifecycle(world, api):
    ticket = await make_ticket(world, categories=[world.billing, world.claims])
    tid = ticket.ticket_id

    # Manager assigns three users in one request, Koushik primary.
    r = await api.as_(world.team_lead).post(
        f"/tickets/{tid}/assignments",
        json={
            "user_ids": [str(world.koushik.user_id), str(world.ravi.user_id), str(world.suresh.user_id)],
            "primary_user_id": str(world.koushik.user_id),
        },
    )
    assert r.status_code == 201, r.text
    users = by_user(r.json())
    assert users["Koushik"]["is_primary"] and not users["Ravi"]["is_primary"]
    assert all(u["resolution_sla"]["status"] == "RUNNING" for u in users.values())

    # Each assignee changes ONLY their own status (secondary is not read-only).
    r = await api.as_(world.ravi).patch(
        f"/tickets/{tid}/assignments/{users['Ravi']['assignment_id']}", json={"status": "PENDING"}
    )
    assert r.status_code == 200, r.text
    r = await api.as_(world.suresh).patch(
        f"/tickets/{tid}/assignments/{users['Suresh']['assignment_id']}", json={"status": "RESOLVED"}
    )
    users = by_user(r.json())
    assert (users["Koushik"]["status"], users["Ravi"]["status"], users["Suresh"]["status"]) == (
        "IN_PROGRESS",
        "PENDING",
        "RESOLVED",
    )
    assert users["Suresh"]["resolution_sla"]["status"] == "COMPLETED"
    assert users["Ravi"]["resolution_sla"]["status"] == "RUNNING"

    # Existing ticket detail still works and still reports the primary.
    r = await api.as_(world.ravi).get(f"/tickets/{tid}")
    assert r.status_code == 200, r.text
    detail = r.json()
    assert detail["agent_id"] == str(world.koushik.user_id)
    assert detail["current_status"] == "IN_PROGRESS"  # a secondary's RESOLVED is not universal
    assert len(detail["assignees"]) == 3 and len(detail["categories"]) == 2

    # Universal close by an authorized manager (existing endpoint).
    r = await api.as_(world.account_manager).post(f"/tickets/{tid}/close")
    assert r.status_code == 200, r.text
    r = await api.as_(world.account_manager).get(f"/tickets/{tid}/assignments")
    body = r.json()
    assert body["is_closed"] and body["ticket_status"] == "CLOSED"
    assert {a["status"] for a in body["assignments"]} == {"CLOSED"}
    assert all(a["resolution_sla"]["status"] == "COMPLETED" for a in body["assignments"])

    # Nothing can be changed on a closed ticket.
    r = await api.as_(world.ravi).patch(
        f"/tickets/{tid}/assignments/{users['Ravi']['assignment_id']}", json={"status": "IN_PROGRESS"}
    )
    assert r.status_code == 400

    # Reopen (existing endpoint): every assignment OPEN with a NEW run; history kept.
    r = await api.as_(world.account_manager).post(f"/tickets/{tid}/reopen")
    assert r.status_code == 200, r.text
    body = (await api.as_(world.account_manager).get(f"/tickets/{tid}/assignments")).json()
    users = by_user(body)
    assert {a["status"] for a in body["assignments"]} == {"OPEN"}
    assert users["Koushik"]["is_primary"]
    for a in body["assignments"]:
        assert [run["run_number"] for run in a["sla_history"]] == [1, 2]
        assert a["resolution_sla"]["run_number"] == 2 and a["resolution_sla"]["status"] == "RUNNING"


async def test_existing_single_assignee_endpoints_still_behave_the_same(world, api):
    ticket = await make_ticket(world)
    tid = ticket.ticket_id

    r = await api.as_(world.koushik).post(f"/tickets/{tid}/claim")
    assert r.status_code == 200, r.text

    # Old status body (no assignment_id) from the primary drives the ticket.
    r = await api.as_(world.koushik).post(f"/tickets/{tid}/status", json={"new_status": "WAITING_FOR_CLIENT"})
    assert r.status_code == 200, r.text
    detail = (await api.as_(world.koushik).get(f"/tickets/{tid}")).json()
    assert detail["current_status"] == "WAITING_FOR_CLIENT"
    sla = (await api.as_(world.koushik).get(f"/tickets/{tid}/sla")).json()
    assert sla["resolution"]["status"] == "PAUSED"  # ticket-level SLA unchanged behaviour

    r = await api.as_(world.team_lead).post(
        f"/tickets/{tid}/transfer", json={"new_agent_id": str(world.ravi.user_id), "reason": "handover"}
    )
    assert r.status_code == 200, r.text
    body = (await api.as_(world.team_lead).get(f"/tickets/{tid}/assignments")).json()
    assert [(a["user_name"], a["is_primary"]) for a in body["assignments"]] == [("Ravi", True)]

    r = await api.as_(world.ravi).get("/tickets", params={"view": "mine", "limit": 200})
    assert r.status_code == 200 and str(tid) in {t["ticket_id"] for t in r.json()}
    r = await api.as_(world.koushik).get("/tickets", params={"view": "mine", "limit": 200})
    assert str(tid) not in {t["ticket_id"] for t in r.json()}


async def test_secondary_sees_ticket_in_my_tickets_and_filters(world, api):
    ticket = await make_ticket(world)
    await api.as_(world.team_lead).post(
        f"/tickets/{ticket.ticket_id}/assignments",
        json={"user_ids": [str(world.koushik.user_id), str(world.ravi.user_id)]},
    )
    r = await api.as_(world.ravi).get("/tickets", params={"view": "mine", "limit": 200})
    assert str(ticket.ticket_id) in {t["ticket_id"] for t in r.json()}
    counts = (await api.as_(world.ravi).get("/tickets/view-counts")).json()
    assert counts["mine"] >= 1

    r = await api.as_(world.team_lead).get(
        "/tickets",
        params={"view": "all", "limit": 200, "assignee_id": str(world.ravi.user_id), "primary_only": "true"},
    )
    assert str(ticket.ticket_id) not in {t["ticket_id"] for t in r.json()}
    r = await api.as_(world.team_lead).get(
        "/tickets", params={"view": "all", "limit": 200, "assignment_status": "OPEN", "assignee_id": str(world.ravi.user_id)}
    )
    assert str(ticket.ticket_id) in {t["ticket_id"] for t in r.json()}


async def test_rbac_and_idor_are_enforced_server_side(world, api):
    ticket = await make_ticket(world)
    other = await make_ticket(world)
    await api.as_(world.team_lead).post(
        f"/tickets/{ticket.ticket_id}/assignments",
        json={"user_ids": [str(world.koushik.user_id), str(world.ravi.user_id)]},
    )
    users = by_user((await api.as_(world.team_lead).get(f"/tickets/{ticket.ticket_id}/assignments")).json())

    # Staff cannot assign people, even by crafting the request.
    r = await api.as_(world.ravi).post(
        f"/tickets/{ticket.ticket_id}/assignments", json={"user_ids": [str(world.suresh.user_id)]}
    )
    assert r.status_code == 403
    # A secondary can't change the primary's status, nor promote themselves.
    r = await api.as_(world.ravi).patch(
        f"/tickets/{ticket.ticket_id}/assignments/{users['Koushik']['assignment_id']}", json={"status": "PENDING"}
    )
    assert r.status_code == 403
    r = await api.as_(world.ravi).patch(
        f"/tickets/{ticket.ticket_id}/assignments/{users['Ravi']['assignment_id']}", json={"is_primary": True}
    )
    assert r.status_code == 403
    # Assignment ids only resolve on their own ticket (no IDOR).
    r = await api.as_(world.team_lead).patch(
        f"/tickets/{other.ticket_id}/assignments/{users['Ravi']['assignment_id']}", json={"status": "PENDING"}
    )
    assert r.status_code == 404
    r = await api.as_(world.team_lead).delete(
        f"/tickets/{other.ticket_id}/assignments/{users['Ravi']['assignment_id']}"
    )
    assert r.status_code == 404
    # Out-of-scope target users and categories are rejected.
    r = await api.as_(world.account_manager).post(
        f"/tickets/{ticket.ticket_id}/assignments", json={"user_ids": [str(world.outsider.user_id)]}
    )
    assert r.status_code == 400
    r = await api.as_(world.team_lead).post(
        f"/tickets/{ticket.ticket_id}/categories", json={"category_id": str(world.claims.category_id)}
    )
    assert r.status_code == 403
    r = await api.as_(world.account_manager).post(
        f"/tickets/{ticket.ticket_id}/categories", json={"category_id": str(uuid.uuid4())}
    )
    assert r.status_code == 400
    # Another client's Account Manager can't touch this ticket at all.
    r = await api.as_(world.other_account_manager).post(
        f"/tickets/{ticket.ticket_id}/assignments", json={"user_ids": [str(world.koushik.user_id)]}
    )
    assert r.status_code == 403
    # Validation errors are clear and atomic.
    r = await api.as_(world.team_lead).post(f"/tickets/{ticket.ticket_id}/assignments", json={"user_ids": []})
    assert r.status_code == 422


async def test_categories_and_primary_management_over_http(world, api):
    ticket = await make_ticket(world)
    tid = ticket.ticket_id
    r = await api.as_(world.account_manager).post(f"/tickets/{tid}/categories", json={"category_id": str(world.claims.category_id)})
    assert r.status_code == 201, r.text
    r = await api.as_(world.account_manager).post(f"/tickets/{tid}/categories", json={"category_id": str(world.claims.category_id)})
    assert r.status_code == 409
    r = await api.as_(world.account_manager).post(
        f"/tickets/{tid}/assignments",
        json={"user_ids": [str(world.koushik.user_id), str(world.suresh.user_id)], "primary_user_id": str(world.koushik.user_id)},
    )
    users = by_user(r.json())

    r = await api.as_(world.account_manager).patch(
        f"/tickets/{tid}/assignments/{users['Suresh']['assignment_id']}", json={"is_primary": True}
    )
    assert r.status_code == 200, r.text
    users = by_user(r.json())
    assert users["Suresh"]["is_primary"] and not users["Koushik"]["is_primary"]
    assert (await api.as_(world.account_manager).get(f"/tickets/{tid}")).json()["agent_id"] == str(world.suresh.user_id)

    r = await api.as_(world.account_manager).delete(f"/tickets/{tid}/assignments/{users['Suresh']['assignment_id']}")
    assert r.status_code == 400  # removing the primary needs a successor
    r = await api.as_(world.account_manager).delete(
        f"/tickets/{tid}/assignments/{users['Suresh']['assignment_id']}",
        params={"new_primary_assignment_id": users["Koushik"]["assignment_id"]},
    )
    assert r.status_code == 200, r.text
    assert [(a["user_name"], a["is_primary"]) for a in r.json()["assignments"]] == [("Koushik", True)]

    r = await api.as_(world.account_manager).delete(f"/tickets/{tid}/categories/{world.claims.category_id}")
    assert r.status_code == 200, r.text
    assert [c["category_name"] for c in r.json()["categories"]] == [world.billing.category_name]


async def test_impersonated_request_audits_actor_and_admin(world, api, monkeypatch):
    from app.core.impersonation_context import set_impersonator

    ticket = await make_ticket(world)
    # What get_current_user does for an impersonation token: effective
    # user = target, impersonator recorded in the request context.
    set_impersonator(world.site_lead.user_id, world.site_lead.name)
    try:
        r = await api.as_(world.team_lead).post(
            f"/tickets/{ticket.ticket_id}/assignments", json={"user_ids": [str(world.koushik.user_id)]}
        )
        assert r.status_code == 201, r.text
    finally:
        set_impersonator(None, None)
    row = (
        await world.session.execute(
            select(AuditLog).where(
                AuditLog.ticket_id == ticket.ticket_id, AuditLog.event_type == AuditEventType.USER_ASSIGNED
            )
        )
    ).scalar_one()
    assert row.actor_id == world.team_lead.user_id
    assert row.impersonator_id == world.site_lead.user_id
