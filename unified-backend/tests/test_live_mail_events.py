# test_live_mail_events.py
#
# Real-time "new mail" signals: published ONLY after the ingestion
# transaction commits, scoped to the users who can see the mail, carrying
# no message content, delivered over the existing per-user SSE stream, and
# never able to affect ingestion or crowd out notifications.

import asyncio
import json
import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.notifications import routes as notification_routes
from app.notifications.sse_manager import (
    _MAIL_EVENT_MAX_QUEUE_FILL,
    NotificationStreamManager,
    get_notification_stream_manager,
)
from app.ticketing.schemas.email import EmailRequest
from app.ticketing.services.email_service import EmailService
from app.ticketing.services.mail_events import (
    MAIL_CREATED,
    MAIL_UPDATED,
    build_mail_event,
    queue_mail_event,
)
from tests.test_email_service_bounce_handling import (
    _bounce_request,
    _client_request,
    _FakeCategoryRepository,
    _FakeClient,
    _FakeClientRepository,
    _FakeInteractionRepository,
    _FakeNotificationService,
    _FakeUserRepository,
    _NeverCalledRuleEngineService,
    _NeverCalledSLAService,
    _RecordingRuleEngineService,
    _RecordingSLAService,
    _settings,
)


def _uid() -> str:
    return str(uuid.uuid4())


def _event(**kw):
    return build_mail_event(
        interaction_id=kw.get("interaction_id", uuid.uuid4()),
        parent_interaction_id=kw.get("parent_interaction_id"),
        ticket_id=kw.get("ticket_id"),
    )


# ---------------------------------------------------------------
# The event itself: ids only, no content
# ---------------------------------------------------------------


def test_new_thread_is_mail_created_and_a_reply_is_mail_updated():
    root = uuid.uuid4()
    created = build_mail_event(interaction_id=root, parent_interaction_id=None, ticket_id=None)
    updated = build_mail_event(
        interaction_id=uuid.uuid4(), parent_interaction_id=root, ticket_id=uuid.uuid4()
    )

    assert created["type"] == MAIL_CREATED and created["thread_id"] == str(root)
    assert updated["type"] == MAIL_UPDATED and updated["thread_id"] == str(root)
    assert updated["ticket_id"] is not None and created["ticket_id"] is None


def test_the_event_carries_ids_and_a_timestamp_only_never_message_content():
    event = _event()

    assert set(event) == {"type", "interaction_id", "thread_id", "ticket_id", "timestamp"}
    blob = json.dumps(event).lower()
    for forbidden in ("subject", "body", "from_email", "@", "name", "message"):
        assert forbidden not in blob


# ---------------------------------------------------------------
# Manager: audience scoping, multi-connection, shedding
# ---------------------------------------------------------------


async def test_only_the_named_audience_receives_a_mail_event():
    manager = NotificationStreamManager()
    owner, stranger = _uid(), _uid()
    q_owner = await manager.subscribe(owner)
    q_stranger = await manager.subscribe(stranger)

    delivered = manager.publish_mail_event({owner}, _event())

    assert delivered == 1
    assert q_owner.qsize() == 1 and q_stranger.qsize() == 0


async def test_global_connections_receive_every_mail_event_without_being_named():
    manager = NotificationStreamManager()
    admin, other = _uid(), _uid()
    q_admin = await manager.subscribe(admin, receives_all_mail=True)
    q_other = await manager.subscribe(other)

    manager.publish_mail_event(set(), _event())

    assert q_admin.qsize() == 1 and q_other.qsize() == 0


async def test_every_tab_of_an_audience_member_gets_its_own_copy():
    manager = NotificationStreamManager()
    user = _uid()
    tabs = [await manager.subscribe(user) for _ in range(3)]

    assert manager.publish_mail_event({user}, _event()) == 3
    assert [q.qsize() for q in tabs] == [1, 1, 1]


async def test_multiple_events_are_delivered_in_order():
    manager = NotificationStreamManager()
    user = _uid()
    queue = await manager.subscribe(user)
    first, second = _event(), _event()

    manager.publish_mail_event({user}, first)
    manager.publish_mail_event({user}, second)

    got = [queue.get_nowait()["interaction_id"] for _ in range(2)]
    assert got == [first["interaction_id"], second["interaction_id"]]


async def test_publishing_never_mutates_the_callers_payload():
    manager = NotificationStreamManager()
    user = _uid()
    await manager.subscribe(user)
    payload = _event()
    snapshot = dict(payload)

    manager.publish_mail_event({user}, payload)

    assert payload == snapshot  # the internal SSE marker is added to a copy


async def test_unsubscribe_removes_the_connection_everywhere():
    manager = NotificationStreamManager()
    admin = _uid()
    queue = await manager.subscribe(admin, receives_all_mail=True)

    await manager.unsubscribe(admin, queue)

    assert manager.publish_mail_event({admin}, _event()) == 0
    assert not manager.has_subscribers(admin) and not manager._all_mail_queues


async def test_mail_events_are_shed_before_a_connection_can_fill_with_them():
    manager = NotificationStreamManager()
    user = _uid()
    queue = await manager.subscribe(user)

    for _ in range(_MAIL_EVENT_MAX_QUEUE_FILL + 25):
        manager.publish_mail_event({user}, _event())

    assert queue.qsize() == _MAIL_EVENT_MAX_QUEUE_FILL
    # ...which leaves room: a real notification still gets through.
    await manager.publish(user, {"notification": {"notification_id": "n1"}, "unread_count": 1})
    assert queue.qsize() == _MAIL_EVENT_MAX_QUEUE_FILL + 1


async def test_no_subscribers_is_a_cheap_no_op():
    assert NotificationStreamManager().publish_mail_event({_uid()}, _event()) == 0


# ---------------------------------------------------------------
# Published only AFTER commit; dropped on rollback
# ---------------------------------------------------------------


@pytest.fixture
def sqlite_session():
    engine = create_engine("sqlite://")
    session = Session(engine)
    session.execute(text("select 1"))  # begin a transaction
    yield session
    session.close()
    engine.dispose()


async def _listen(user):
    return await get_notification_stream_manager().subscribe(user)


async def _stop(user, queue):
    await get_notification_stream_manager().unsubscribe(user, queue)


async def test_event_is_published_only_after_commit(sqlite_session):
    user = _uid()
    queue = await _listen(user)
    try:
        queue_mail_event(SimpleNamespace(sync_session=sqlite_session), _event(), {user})

        assert queue.qsize() == 0  # queued, NOT published, before the commit
        sqlite_session.commit()
        assert queue.qsize() == 1
        assert queue.get_nowait()["_sse_event"] == "mail"
    finally:
        await _stop(user, queue)


async def test_a_rolled_back_transaction_never_publishes(sqlite_session):
    user = _uid()
    queue = await _listen(user)
    try:
        queue_mail_event(SimpleNamespace(sync_session=sqlite_session), _event(), {user})
        sqlite_session.rollback()
        sqlite_session.execute(text("select 1"))
        sqlite_session.commit()  # a LATER commit must not resurrect it

        assert queue.qsize() == 0
    finally:
        await _stop(user, queue)


async def test_each_event_is_published_exactly_once(sqlite_session):
    user = _uid()
    queue = await _listen(user)
    try:
        queue_mail_event(SimpleNamespace(sync_session=sqlite_session), _event(), {user})
        sqlite_session.commit()
        sqlite_session.execute(text("select 1"))
        sqlite_session.commit()

        assert queue.qsize() == 1
    finally:
        await _stop(user, queue)


def test_queueing_on_an_unsuitable_session_is_silently_ignored():
    queue_mail_event(object(), _event(), {_uid()})  # no sync_session: no error


# ---------------------------------------------------------------
# Ingestion (EmailService.receive_email) queues exactly the right events
# ---------------------------------------------------------------


class _RecordingDb:
    """Stands in for the AsyncSession: a real `.sync_session.info` dict."""

    def __init__(self):
        self.sync_session = SimpleNamespace(info={})

    def add(self, obj):
        pass

    async def flush(self):
        pass

    async def refresh(self, obj):
        pass


class _Repo(_FakeInteractionRepository):
    def __init__(self, db):
        super().__init__()
        self.db = db


def _queued(db):
    return db.sync_session.info.get("utms_pending_mail_events", [])


def _service(monkeypatch, db, *, rules=None, sla=None, client=None, notifications=None):
    monkeypatch.setattr(
        "app.ticketing.services.email_service.get_settings", lambda: _settings()
    )
    clients = {"familyfirst@probeps.com": client} if client else {}
    return EmailService(
        interaction_repository=_Repo(db),
        client_repository=_FakeClientRepository(clients),
        attachment_service=None,
        user_repository=_FakeUserRepository({}),
        notification_service=notifications or _FakeNotificationService(),
        sla_service=sla or _RecordingSLAService(),
        rule_engine_service=rules or _RecordingRuleEngineService(),
        category_repository=_FakeCategoryRepository(),
    )


def _client():
    return _FakeClient(uuid.uuid4(), "Family First", "familyfirst@probeps.com", uuid.uuid4())


def _mail():
    return _client_request(
        to_email="familyfirst@probeps.com", landed_mailbox="familyfirst@probeps.com"
    )


async def test_new_mail_queues_one_created_event_for_the_owning_account_manager(monkeypatch):
    db, client = _RecordingDb(), _client()
    service = _service(monkeypatch, db, client=client)

    await service.receive_email(_mail())

    [(payload, audience)] = _queued(db)
    assert payload["type"] == MAIL_CREATED
    assert audience == {str(client.account_manager_id)}
    # no PHI in what will be sent
    assert "Question about my account" not in json.dumps(payload)
    assert "patient@example.com" not in json.dumps(payload)


async def test_a_failed_ingestion_queues_nothing(monkeypatch):
    class _Boom:
        async def evaluate_and_execute_for_email(self, **kwargs):
            raise RuntimeError("rule engine down")

    db, client = _RecordingDb(), _client()
    service = _service(monkeypatch, db, client=client, rules=_Boom())

    with pytest.raises(RuntimeError):
        await service.receive_email(_mail())

    assert _queued(db) == []


async def test_a_duplicate_message_queues_no_second_event(monkeypatch):
    db, client = _RecordingDb(), _client()
    service = _service(monkeypatch, db, client=client)
    service.interaction_repository.exists_by_message_id = lambda _id: _async(True)

    with pytest.raises(ValueError):
        await service.receive_email(_mail())

    assert _queued(db) == []


async def _async(value):
    return value


async def test_bounces_and_read_receipts_never_produce_mail_events(monkeypatch):
    db = _RecordingDb()
    service = _service(
        monkeypatch, db, rules=_NeverCalledRuleEngineService(), sla=_NeverCalledSLAService()
    )

    await service.receive_email(_bounce_request())
    await service.receive_email(
        EmailRequest(
            to_email="ticketing@probeps.com", from_email="r@example.com", subject="Read: x",
            body="b", message_id=f"<{uuid.uuid4().hex}@example.com>", is_read_receipt=True,
        )
    )

    assert _queued(db) == []


# ---------------------------------------------------------------
# The real SSE route: authentication, scoping, cleanup
# ---------------------------------------------------------------


def _user(role: str):
    return SimpleNamespace(user_id=uuid.uuid4(), role=SimpleNamespace(name=role))


class _Request:
    async def is_disconnected(self):
        return False


async def _open_stream(user):
    response = await notification_routes.stream_notifications(
        request=_Request(), current_user=user
    )
    return response, response.body_iterator


async def _next_chunk(iterator, timeout=2.0):
    return await asyncio.wait_for(iterator.__anext__(), timeout)


async def test_a_connected_client_receives_mail_created_as_a_named_sse_event():
    manager = get_notification_stream_manager()
    am = _user("Account Manager")
    response, stream = await _open_stream(am)
    try:
        assert response.media_type == "text/event-stream"
        payload = _event()
        manager.publish_mail_event({str(am.user_id)}, payload)

        chunk = await _next_chunk(stream)

        assert chunk.startswith("event: mail\n")
        body = json.loads(chunk.split("data: ", 1)[1])
        assert body["type"] == MAIL_CREATED and body["interaction_id"] == payload["interaction_id"]
        assert "_sse_event" not in body  # the internal marker never leaves the server
    finally:
        await stream.aclose()


async def test_a_user_outside_the_audience_receives_nothing():
    manager = get_notification_stream_manager()
    owner, stranger = _user("Account Manager"), _user("Account Manager")
    _, stranger_stream = await _open_stream(stranger)
    try:
        manager.publish_mail_event({str(owner.user_id)}, _event())

        with pytest.raises(asyncio.TimeoutError):
            await _next_chunk(stranger_stream, timeout=0.3)
    finally:
        await stranger_stream.aclose()


@pytest.mark.parametrize("role", ["Site Lead", "Super Admin"])
async def test_global_roles_receive_every_mail_event(role):
    manager = get_notification_stream_manager()
    admin = _user(role)
    _, stream = await _open_stream(admin)
    try:
        manager.publish_mail_event(set(), _event())
        assert (await _next_chunk(stream)).startswith("event: mail\n")
    finally:
        await stream.aclose()


@pytest.mark.parametrize("role", ["Staff", "Team Lead", "Account Manager"])
async def test_other_roles_are_not_treated_as_receive_everything(role):
    manager = get_notification_stream_manager()
    user = _user(role)
    _, stream = await _open_stream(user)
    try:
        manager.publish_mail_event(set(), _event())
        with pytest.raises(asyncio.TimeoutError):
            await _next_chunk(stream, timeout=0.3)
    finally:
        await stream.aclose()


async def test_notifications_still_use_their_original_event_name():
    manager = get_notification_stream_manager()
    user = _user("Account Manager")
    _, stream = await _open_stream(user)
    try:
        await manager.publish(
            str(user.user_id), {"notification": {"notification_id": "n1"}, "unread_count": 1}
        )
        chunk = await _next_chunk(stream)
        assert chunk.startswith("event: notification\n")
    finally:
        await stream.aclose()


async def test_closing_the_stream_unsubscribes_it():
    manager = get_notification_stream_manager()
    user = _user("Account Manager")
    _, stream = await _open_stream(user)
    assert manager.has_subscribers(str(user.user_id))
    # Starlette always iterates a streaming body; do the same so the
    # generator is running (and its `finally` can clean up) when closed.
    manager.publish_mail_event({str(user.user_id)}, _event())
    await _next_chunk(stream)

    await stream.aclose()

    assert not manager.has_subscribers(str(user.user_id))


async def test_multiple_connected_clients_each_get_the_event():
    manager = get_notification_stream_manager()
    a, b = _user("Account Manager"), _user("Account Manager")
    _, stream_a = await _open_stream(a)
    _, stream_b = await _open_stream(b)
    try:
        manager.publish_mail_event({str(a.user_id), str(b.user_id)}, _event())
        assert (await _next_chunk(stream_a)).startswith("event: mail\n")
        assert (await _next_chunk(stream_b)).startswith("event: mail\n")
    finally:
        await stream_a.aclose()
        await stream_b.aclose()


def test_the_stream_route_still_requires_the_query_token_auth_dependency():
    from app.dependencies.auth import get_current_user_sse

    route = next(r for r in notification_routes.router.routes if r.path == "/notifications/stream")
    assert get_current_user_sse in [d.call for d in route.dependant.dependencies]


async def test_an_invalid_token_cannot_open_the_stream():
    from fastapi import HTTPException

    from app.dependencies.auth import get_current_user_sse

    with pytest.raises(HTTPException) as caught:
        await get_current_user_sse(token="not-a-real-jwt")

    assert caught.value.status_code == 401


# ---------------------------------------------------------------
# The real AsyncSession path (what the poller / API / webhook commit with)
# ---------------------------------------------------------------


async def test_the_hook_fires_for_a_real_async_session_commit_and_not_for_rollback():
    from app.database.session import AsyncSessionLocal, engine

    user = _uid()
    queue = await _listen(user)
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("select 1"))
            queue_mail_event(session, _event(), {user})
            assert queue.qsize() == 0
            await session.commit()
            assert queue.qsize() == 1

        async with AsyncSessionLocal() as session:
            await session.execute(text("select 1"))
            queue_mail_event(session, _event(), {user})
            await session.rollback()
            await session.execute(text("select 1"))
            await session.commit()
            assert queue.qsize() == 1  # nothing new from the rolled-back one
    finally:
        await _stop(user, queue)
        await engine.dispose()
