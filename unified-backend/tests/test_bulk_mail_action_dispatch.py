# test_bulk_mail_action_dispatch.py
#
# No-DB coverage of BulkMailActionService: it is a dispatcher over the
# EXISTING single-interaction services, so these tests fake those services
# and assert the contract — one existing call per interaction, independent
# authorization/failure per item, partial success, safe error messages,
# de-duplication, and no merging of unrelated interactions.

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.ticketing.schemas.bulk_mail_action import (
    BulkMailActionRequest,
)
from app.ticketing.services import bulk_mail_action_service as bulk_module
from app.ticketing.services.bulk_mail_action_service import (
    COULD_NOT_PROCESS,
    FOLDER_NOT_AVAILABLE,
    NOT_AVAILABLE,
    NOT_ELIGIBLE,
    BulkMailActionService,
)


class _Savepoint:
    """Stand-in for AsyncSession.begin_nested(): records rollbacks."""

    def __init__(self, db):
        self.db = db

    async def __aenter__(self):
        self.db.entered += 1
        return self

    async def __aexit__(self, exc_type, exc, tb):
        if exc_type is not None:
            self.db.rolled_back += 1
        return False  # never swallow — the service must see the error


class _FakeDb:
    def __init__(self):
        self.entered = 0
        self.rolled_back = 0

    def begin_nested(self):
        return _Savepoint(self)


def _interaction(subject="Hello", ticket_id=None, parent=None, client_id=None):
    return SimpleNamespace(
        interaction_id=uuid4(),
        subject=subject,
        ticket_id=ticket_id,
        parent_interaction_id=parent,
        client_id=client_id,
    )


def _build(interactions=()):
    db = _FakeDb()
    by_id = {i.interaction_id: i for i in interactions}

    interaction_repository = MagicMock()
    interaction_repository.get_by_id = AsyncMock(side_effect=lambda i: by_id.get(i))

    read_status = MagicMock()
    read_status.mark_read = AsyncMock()
    read_status.mark_unread = AsyncMock()

    mark_service = MagicMock()
    mark_service.set_flag = AsyncMock()
    mark_service.set_pin = AsyncMock()

    interaction_service = MagicMock()
    interaction_service.archive_interaction = AsyncMock()
    interaction_service.set_interaction_folder = AsyncMock()
    interaction_service.hide_interaction = AsyncMock()
    interaction_service.restore_interaction = AsyncMock()

    inbox_ticket_service = MagicMock()
    inbox_ticket_service.create_ticket_from_interaction = AsyncMock(
        side_effect=lambda req, current_user: SimpleNamespace(ticket_id=uuid4())
    )
    inbox_ticket_service.attach_to_existing_ticket = AsyncMock(
        side_effect=lambda ticket_id, request, current_user: SimpleNamespace(
            ticket_id=ticket_id
        )
    )

    mail_folder_repository = MagicMock()
    mail_folder_repository.get_by_id = AsyncMock(return_value=SimpleNamespace())

    service = BulkMailActionService(
        db,
        interaction_repository=interaction_repository,
        ticket_repository=MagicMock(),
        client_repository=MagicMock(),
        mail_folder_repository=mail_folder_repository,
        rule_repository=MagicMock(),
        distribution_list_repository=MagicMock(),
        read_status_service=read_status,
        message_mark_service=mark_service,
        interaction_service=interaction_service,
        inbox_ticket_service=inbox_ticket_service,
    )
    # View access is covered by access_control's own tests and the DB tests.
    service._ensure_can_view = AsyncMock()
    return service, db


_USER = SimpleNamespace(user_id=uuid4())


def _by_id(result):
    return {r.interaction_id: r for r in result.results}


def _req(ids, action, **kw):
    return BulkMailActionRequest(interaction_ids=ids, action=action, **kw)


# --------------------------- schema ---------------------------------


def test_attach_requires_ticket_id():
    with pytest.raises(ValidationError):
        _req([uuid4()], "attach_to_ticket")
    with pytest.raises(ValidationError):
        _req([uuid4()], "link_ticket")


def test_create_ticket_requires_ticket_type():
    with pytest.raises(ValidationError):
        _req([uuid4()], "create_ticket")


def test_empty_and_oversized_selection_rejected():
    with pytest.raises(ValidationError):
        _req([], "archive")
    with pytest.raises(ValidationError):
        _req([uuid4() for _ in range(101)], "archive")


# ----------------------- mail management ----------------------------


async def test_mark_read_and_unread_run_once_per_interaction():
    service, _ = _build()
    ids = [uuid4(), uuid4(), uuid4()]

    out = await service.run(_req(ids, "mark_read"), _USER)
    assert (out.requested, out.succeeded, out.failed) == (3, 3, 0)
    assert service.read_status_service.mark_read.await_count == 3
    assert service._ensure_can_view.await_count == 3

    out = await service.run(_req(ids, "mark_unread"), _USER)
    assert out.succeeded == 3
    assert service.read_status_service.mark_unread.await_count == 3


async def test_duplicate_ids_processed_once():
    service, _ = _build()
    a, b = uuid4(), uuid4()
    out = await service.run(_req([a, b, a, b, a], "archive"), _USER)
    assert out.requested == 2
    assert service.interaction_service.archive_interaction.await_count == 2


async def test_archive_partial_success_with_safe_reasons():
    service, db = _build()
    ok1, ok2, forbidden, ticketed, boom = (uuid4() for _ in range(5))

    async def archive(*, interaction_id, current_user):
        if interaction_id == forbidden:
            raise HTTPException(403, "You do not have access to Acme Corp's mail.")
        if interaction_id == ticketed:
            raise HTTPException(400, "Interaction already linked to ticket T-1234.")
        if interaction_id == boom:
            raise RuntimeError("db exploded with secret details")

    service.interaction_service.archive_interaction = AsyncMock(side_effect=archive)

    out = await service.run(
        _req([ok1, forbidden, ok2, ticketed, boom], "archive"), _USER
    )

    assert (out.requested, out.succeeded, out.failed) == (5, 2, 3)
    by_id = {r.interaction_id: r for r in out.results}
    assert by_id[ok1].status == by_id[ok2].status == "success"
    assert by_id[forbidden].reason == NOT_AVAILABLE
    assert by_id[ticketed].reason == NOT_ELIGIBLE
    assert by_id[boom].reason == COULD_NOT_PROCESS
    # Nothing identifying leaks out of the original errors.
    for r in out.results:
        assert "Acme" not in (r.reason or "") and "T-1234" not in (r.reason or "")
        assert "secret" not in (r.reason or "")
    # Each failing item rolled back only its own savepoint.
    assert db.entered == 5 and db.rolled_back == 3
    # Order preserved.
    assert [r.interaction_id for r in out.results] == [ok1, forbidden, ok2, ticketed, boom]


async def test_unauthorized_interaction_never_blocks_authorized_ones():
    service, _ = _build()
    allowed, denied = uuid4(), uuid4()

    async def view(interaction_id, current_user):
        if interaction_id == denied:
            raise HTTPException(403, "no")

    service._ensure_can_view = AsyncMock(side_effect=view)
    out = await service.run(_req([denied, allowed], "mark_read"), _USER)
    assert [r.status for r in out.results] == ["failed", "success"]
    # The denied interaction was never marked.
    service.read_status_service.mark_read.assert_awaited_once()
    assert service.read_status_service.mark_read.await_args.args[0] == allowed


async def test_move_passes_folder_to_existing_service_per_interaction():
    service, _ = _build()
    folder = uuid4()
    ids = [uuid4(), uuid4()]
    service._folder_is_usable = AsyncMock(return_value=True)

    out = await service.run(_req(ids, "move", folder_id=folder), _USER)
    assert out.succeeded == 2
    calls = service.interaction_service.set_interaction_folder.await_args_list
    assert [c.kwargs["interaction_id"] for c in calls] == ids
    assert all(c.kwargs["request"].folder_id == folder for c in calls)


async def test_move_to_unauthorized_folder_fails_every_item_without_calling_service():
    service, _ = _build()
    service._folder_is_usable = AsyncMock(return_value=False)
    out = await service.run(_req([uuid4(), uuid4()], "move", folder_id=uuid4()), _USER)
    assert (out.succeeded, out.failed) == (0, 2)
    assert {r.reason for r in out.results} == {FOLDER_NOT_AVAILABLE}
    service.interaction_service.set_interaction_folder.assert_not_awaited()


async def test_move_with_no_folder_unfiles_and_skips_folder_check():
    service, _ = _build()
    service._folder_is_usable = AsyncMock(return_value=False)
    out = await service.run(_req([uuid4()], "move"), _USER)
    assert out.succeeded == 1
    service._folder_is_usable.assert_not_awaited()


async def test_folder_visibility_uses_existing_ensure_visible(monkeypatch):
    service, _ = _build()
    ensure_visible = AsyncMock(side_effect=HTTPException(404, "Folder not found."))
    monkeypatch.setattr(
        bulk_module.MailFolderService, "ensure_visible", ensure_visible
    )
    assert await service._folder_is_usable(uuid4(), _USER) is False

    ensure_visible.side_effect = None
    assert await service._folder_is_usable(uuid4(), _USER) is True

    service.mail_folder_repository.get_by_id = AsyncMock(return_value=None)
    assert await service._folder_is_usable(uuid4(), _USER) is False


async def test_delete_hides_each_interaction_with_its_own_ticket_id():
    ticket = uuid4()
    pre_ticket = _interaction()
    ticketed = _interaction(ticket_id=ticket)
    service, _ = _build([pre_ticket, ticketed])

    out = await service.run(
        _req([pre_ticket.interaction_id, ticketed.interaction_id], "delete"), _USER
    )
    assert out.succeeded == 2
    calls = service.interaction_service.hide_interaction.await_args_list
    assert [c.kwargs["ticket_id"] for c in calls] == [None, ticket]


async def test_restore_calls_the_single_restore_with_its_own_ticket_id():
    ticket = uuid4()
    pre_ticket = _interaction()
    ticketed = _interaction(ticket_id=ticket)
    service, _ = _build([pre_ticket, ticketed])

    out = await service.run(
        _req([pre_ticket.interaction_id, ticketed.interaction_id], "restore"), _USER
    )
    assert out.succeeded == 2
    calls = service.interaction_service.restore_interaction.await_args_list
    assert [c.kwargs["ticket_id"] for c in calls] == [None, ticket]


async def test_flag_and_pin_actions_call_the_mark_service_after_the_view_check():
    mail = _interaction()
    service, _ = _build([mail])
    for action, method, flag in (
        ("flag", "set_flag", True),
        ("unflag", "set_flag", False),
        ("pin", "set_pin", True),
        ("unpin", "set_pin", False),
    ):
        out = await service.run(_req([mail.interaction_id], action), _USER)
        assert out.succeeded == 1
        getattr(service.message_mark_service, method).assert_awaited_with(
            mail.interaction_id, flag, _USER
        )
    assert service._ensure_can_view.await_count == 4


async def test_delete_missing_interaction_fails_safely():
    service, _ = _build()
    out = await service.run(_req([uuid4()], "delete"), _USER)
    assert out.results[0].status == "failed"
    assert out.results[0].reason == NOT_AVAILABLE


# --------------------------- ticketing ------------------------------


async def test_create_ticket_makes_one_ticket_per_email_titled_by_its_subject():
    a = _interaction("Client A invoice")
    b = _interaction("Client B outage")
    c = _interaction(None)
    service, _ = _build([a, b, c])

    out = await service.run(
        _req(
            [a.interaction_id, b.interaction_id, c.interaction_id],
            "create_ticket",
            ticket_type="Billing",
            current_priority="HIGH",
        ),
        _USER,
    )

    assert out.succeeded == 3
    calls = service.inbox_ticket_service.create_ticket_from_interaction.await_args_list
    assert len(calls) == 3  # never merged into one ticket
    reqs = [c.args[0] for c in calls]
    assert [r.interaction_id for r in reqs] == [
        a.interaction_id, b.interaction_id, c.interaction_id
    ]
    assert [r.title for r in reqs] == ["Client A invoice", "Client B outage", "(no subject)"]
    assert {r.ticket_type for r in reqs} == {"Billing"}
    # Distinct ticket per interaction is reported back.
    assert len({r.ticket_id for r in out.results}) == 3


async def test_create_ticket_failure_is_isolated():
    a, b = _interaction("A"), _interaction("B")
    service, db = _build([a, b])

    async def create(req, current_user):
        if req.interaction_id == b.interaction_id:
            raise HTTPException(400, "Interaction already has a ticket.")
        return SimpleNamespace(ticket_id=uuid4())

    service.inbox_ticket_service.create_ticket_from_interaction = AsyncMock(
        side_effect=create
    )
    out = await service.run(
        _req([a.interaction_id, b.interaction_id], "create_ticket", ticket_type="X"),
        _USER,
    )
    assert [r.status for r in out.results] == ["success", "failed"]
    assert out.results[1].reason == NOT_ELIGIBLE
    assert db.rolled_back == 1


@pytest.mark.parametrize("action", ["link_ticket", "attach_to_ticket"])
async def test_link_and_attach_both_use_the_existing_attach_workflow(action):
    mails = [_interaction(), _interaction()]
    service, _ = _build(mails)
    ticket = uuid4()
    agent = uuid4()
    ids = [m.interaction_id for m in mails]

    out = await service.run(
        _req(ids, action, ticket_id=ticket, new_agent_id=agent, new_priority="HIGH"),
        _USER,
    )
    assert out.succeeded == 2
    calls = service.inbox_ticket_service.attach_to_existing_ticket.await_args_list
    assert [c.kwargs["ticket_id"] for c in calls] == [ticket, ticket]
    assert [c.kwargs["request"].interaction_id for c in calls] == ids
    # Reopen options are forwarded verbatim to the existing workflow, which
    # owns the Closed -> In Progress reopening; bulk adds no reopen logic.
    assert all(c.kwargs["request"].new_agent_id == agent for c in calls)
    assert {r.ticket_id for r in out.results} == {ticket}


async def test_attach_mixed_result_one_rejected_others_succeed():
    mails = [_interaction(), _interaction(), _interaction()]
    service, _ = _build(mails)
    a, b, c = (m.interaction_id for m in mails)

    async def attach(ticket_id, request, current_user):
        if request.interaction_id == c:
            raise HTTPException(403, "Ticket belongs to another client.")
        return SimpleNamespace(ticket_id=ticket_id)

    service.inbox_ticket_service.attach_to_existing_ticket = AsyncMock(
        side_effect=attach
    )
    out = await service.run(_req([a, b, c], "attach_to_ticket", ticket_id=uuid4()), _USER)
    assert [r.status for r in out.results] == ["success", "success", "failed"]
    assert (out.succeeded, out.failed) == (2, 1)
    assert out.results[2].reason == NOT_AVAILABLE
    assert "client" not in out.results[2].reason.lower()


async def test_attach_rejects_an_interaction_from_a_different_client_than_the_ticket():
    client_a, client_b = uuid4(), uuid4()
    same = _interaction(client_id=client_a)
    other = _interaction(client_id=client_b)
    category_mail = _interaction(client_id=None)
    service, _ = _build([same, other, category_mail])
    ticket = SimpleNamespace(client_company_id=client_a)
    service.ticket_repository.get_by_id = AsyncMock(return_value=ticket)

    out = await service.run(
        _req(
            [same.interaction_id, other.interaction_id, category_mail.interaction_id],
            "attach_to_ticket",
            ticket_id=uuid4(),
        ),
        _USER,
    )

    res = _by_id(out)
    assert res[same.interaction_id].status == "success"
    assert res[other.interaction_id].status == "failed"
    assert res[other.interaction_id].reason == NOT_ELIGIBLE
    # Category-mailbox mail has no client to compare — existing workflow decides.
    assert res[category_mail.interaction_id].status == "success"
    attached = [
        c.kwargs["request"].interaction_id
        for c in service.inbox_ticket_service.attach_to_existing_ticket.await_args_list
    ]
    assert other.interaction_id not in attached
