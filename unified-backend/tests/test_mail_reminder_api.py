# test_mail_reminder_api.py
#
# HTTP-level coverage for /mail-reminders: routing, status codes, request
# validation, the "no user_id in the body" rule, per-user isolation and
# the auth dependency. The router is mounted alone on a throwaway FastAPI
# app with get_current_agent / get_db overridden and the service built on
# the in-memory fakes from test_mail_reminder_service (same cross-import
# convention as test_live_mail_events.py). The real-database path is
# covered by test_mail_reminder_db.py.

import uuid
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from fastapi import FastAPI, HTTPException

from app.database.session import get_db
from app.dependencies.auth import get_current_agent
from app.ticketing.api import mail_reminder as api_module
from app.ticketing.services.mail_reminder_service import MailReminderService
from tests.test_mail_reminder_service import (
    Env,
    FakeInteractionRepository,
    FakeReminderRepository,
    make_user,
)


def iso(**delta) -> str:
    return (datetime.now(timezone.utc) + timedelta(**delta)).isoformat()


@pytest.fixture
def world(monkeypatch):
    env = Env()
    state = {"user": make_user()}

    app = FastAPI()
    app.include_router(api_module.router)

    async def _current_user():
        if state["user"] is None:
            raise HTTPException(status_code=401, detail="Not authenticated")
        return state["user"]

    commits = []

    class _FakeDb:
        async def commit(self):
            commits.append(1)

    async def _db():
        yield _FakeDb()

    app.state.commits = commits
    app.dependency_overrides[get_current_agent] = _current_user
    app.dependency_overrides[get_db] = _db
    monkeypatch.setattr(api_module, "build_mail_reminder_service", lambda db: env.service)

    client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    )
    return SimpleWorld(env, state, client)


class SimpleWorld:
    def __init__(self, env, state, client):
        self.env, self.state, self.client = env, state, client

    def login(self, user):
        self.state["user"] = user

    @property
    def root_id(self):
        return str(self.env.root.interaction_id)


async def create(world, **over):
    body = {"interaction_id": world.root_id, "remind_at": iso(hours=2)}
    body.update(over)
    return await world.client.post("/mail-reminders", json=body)


async def test_create_returns_201_and_reminder(world):  # R-001
    r = await create(world)

    assert r.status_code == 201
    body = r.json()
    assert body["status"] == "ACTIVE"
    assert body["interaction_id"] == world.root_id
    assert body["snooze_count"] == 0
    assert body["reminder_id"]
    assert "user_id" not in body  # ownership is never echoed back or accepted


async def test_user_id_in_body_is_ignored(world):  # R-023
    me = world.state["user"]
    intruder = str(uuid.uuid4())

    r = await create(world, user_id=intruder)

    assert r.status_code == 201
    stored = next(iter(world.env.repo.rows.values()))
    assert stored.user_id == me.user_id
    assert str(stored.user_id) != intruder


ALL_ROUTES = [
    ("POST", "/mail-reminders"),
    ("GET", "/mail-reminders"),
    ("GET", "/mail-reminders/{id}"),
    ("PATCH", "/mail-reminders/{id}"),
    ("DELETE", "/mail-reminders/{id}"),
    ("POST", "/mail-reminders/{id}/snooze"),
    ("POST", "/mail-reminders/{id}/dismiss"),
]


async def test_every_route_rejects_requests_without_credentials():  # R-022
    # Real get_current_agent dependency (NOT overridden): no bearer token
    # must be refused before any handler or database work runs.
    app = FastAPI()
    app.include_router(api_module.router)

    async def _db():
        yield object()

    app.dependency_overrides[get_db] = _db
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        for method, path in ALL_ROUTES:
            resp = await client.request(
                method, path.format(id=uuid.uuid4()), json={}
            )
            assert resp.status_code in (401, 403), (method, path, resp.status_code)


async def test_invalid_bearer_token_is_rejected():  # R-022
    app = FastAPI()
    app.include_router(api_module.router)

    async def _db():
        yield object()

    app.dependency_overrides[get_db] = _db
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get(
            "/mail-reminders", headers={"Authorization": "Bearer not-a-real-token"}
        )
    assert resp.status_code in (401, 403)


async def test_naive_datetime_is_422(world):  # R-007
    r = await create(world, remind_at="2030-01-01T09:00:00")
    assert r.status_code == 422


async def test_past_datetime_is_422(world):  # R-002
    r = await create(world, remind_at=iso(hours=-1))
    assert r.status_code == 422


async def test_garbage_datetime_is_422(world):
    assert (await create(world, remind_at="tomorrow")).status_code == 422


async def test_bad_interaction_id_is_422_and_unknown_is_404(world):
    assert (await create(world, interaction_id="not-a-uuid")).status_code == 422
    assert (await create(world, interaction_id=str(uuid.uuid4()))).status_code == 404  # R-010


async def test_duplicate_is_409(world):  # R-013
    assert (await create(world)).status_code == 201
    assert (await create(world)).status_code == 409


async def test_get_and_list_own(world):  # R-021
    rid = (await create(world)).json()["reminder_id"]

    got = await world.client.get(f"/mail-reminders/{rid}")
    listed = await world.client.get("/mail-reminders", params={"status": "ACTIVE"})

    assert got.status_code == 200 and got.json()["reminder_id"] == rid
    assert [x["reminder_id"] for x in listed.json()] == [rid]


async def test_list_status_query_param_is_named_status(world):
    await create(world)
    assert (await world.client.get("/mail-reminders?status=CANCELED")).json() == []
    assert (await world.client.get("/mail-reminders?status=BOGUS")).status_code == 422
    other = str(uuid.uuid4())
    assert (await world.client.get(f"/mail-reminders?interaction_id={other}")).json() == []


async def test_patch_updates_time(world):  # R-015
    rid = (await create(world)).json()["reminder_id"]
    new = iso(days=3)

    r = await world.client.patch(f"/mail-reminders/{rid}", json={"remind_at": new})

    assert r.status_code == 200
    assert datetime.fromisoformat(r.json()["remind_at"]) == datetime.fromisoformat(new)


async def test_delete_cancels_with_204(world):  # R-017
    rid = (await create(world)).json()["reminder_id"]

    r = await world.client.delete(f"/mail-reminders/{rid}")

    assert r.status_code == 204 and r.content == b""
    got = await world.client.get(f"/mail-reminders/{rid}")
    assert got.json()["status"] == "CANCELED"
    assert (await world.client.patch(f"/mail-reminders/{rid}", json={"remind_at": iso(days=1)})).status_code == 409


async def test_snooze_by_minutes_and_by_time(world):  # R-018
    rid = (await create(world)).json()["reminder_id"]

    a = await world.client.post(f"/mail-reminders/{rid}/snooze", json={"minutes": 60})
    b = await world.client.post(
        f"/mail-reminders/{rid}/snooze", json={"remind_at": iso(days=1)}
    )

    assert a.status_code == b.status_code == 200
    assert b.json()["snooze_count"] == 2


@pytest.mark.parametrize(
    "body",
    [{}, {"minutes": 0}, {"minutes": -5}, {"minutes": 5, "remind_at": "2099-01-01T00:00:00+00:00"}],
)
async def test_invalid_snooze_bodies_are_422(world, body):  # R-019
    rid = (await create(world)).json()["reminder_id"]
    r = await world.client.post(f"/mail-reminders/{rid}/snooze", json=body)
    assert r.status_code == 422


async def test_dismiss_requires_fired(world):  # R-020
    rid = (await create(world)).json()["reminder_id"]
    assert (await world.client.post(f"/mail-reminders/{rid}/dismiss")).status_code == 409

    next(iter(world.env.repo.rows.values())).status = "FIRED"
    r = await world.client.post(f"/mail-reminders/{rid}/dismiss")

    assert r.status_code == 200 and r.json()["status"] == "DISMISSED"


async def test_another_users_reminder_is_404_on_every_route(world):  # R-003
    rid = (await create(world)).json()["reminder_id"]
    next(iter(world.env.repo.rows.values())).status = "FIRED"

    world.login(make_user())  # user B

    assert (await world.client.get(f"/mail-reminders/{rid}")).status_code == 404
    assert (await world.client.patch(f"/mail-reminders/{rid}", json={"remind_at": iso(days=1)})).status_code == 404
    assert (await world.client.delete(f"/mail-reminders/{rid}")).status_code == 404
    assert (await world.client.post(f"/mail-reminders/{rid}/snooze", json={"minutes": 5})).status_code == 404
    assert (await world.client.post(f"/mail-reminders/{rid}/dismiss")).status_code == 404
    assert (await world.client.get("/mail-reminders")).json() == []


async def test_inaccessible_email_is_404(world):  # R-011
    world.env.can_view = False
    assert (await create(world)).status_code == 404
    assert world.env.repo.rows == {}


async def test_every_write_is_committed_before_the_response_is_returned(world):
    """
    The UI refetches right after a write returns, so each mutating route must
    commit itself (get_db's own commit runs only after the response is sent).
    """

    commits = world.client._transport.app.state.commits

    created = await create(world)
    rid = created.json()["reminder_id"]
    assert len(commits) == 1  # POST

    await world.client.patch(f"/mail-reminders/{rid}", json={"remind_at": iso(days=2)})
    assert len(commits) == 2  # PATCH

    await world.client.post(f"/mail-reminders/{rid}/snooze", json={"minutes": 30})
    assert len(commits) == 3  # snooze

    await world.client.delete(f"/mail-reminders/{rid}")
    assert len(commits) == 4  # DELETE

    again = (await create(world)).json()["reminder_id"]
    next(r for r in world.env.repo.rows.values() if str(r.reminder_id) == again).status = "FIRED"
    await world.client.post(f"/mail-reminders/{again}/dismiss")
    assert len(commits) == 6  # POST + dismiss


async def test_failed_requests_do_not_commit(world):
    commits = world.client._transport.app.state.commits

    await create(world, remind_at=iso(hours=-1))  # 422
    await world.client.get(f"/mail-reminders/{uuid.uuid4()}")  # 404 read
    await world.client.delete(f"/mail-reminders/{uuid.uuid4()}")  # 404 write

    assert commits == []
