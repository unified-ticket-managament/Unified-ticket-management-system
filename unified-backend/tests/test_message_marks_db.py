# test_message_marks_db.py
#
# Real-DB (rolled-back) coverage of per-user Flag / Pin: they ride the
# existing bulk-action dispatcher (so they get its per-item view check),
# are personal to the caller, pinned mail sorts first, and un-marking
# leaves no stray row. Same prerequisites as test_bulk_mail_action_db.py
# (throwaway DB migrated to head, never the shared RDS). Run on its own.

from sqlalchemy import select

from app.ticketing.models.message_mark import MessageMark
from app.ticketing.repositories.interaction_repository import InteractionRepository
from app.ticketing.repositories.message_mark_repository import MessageMarkRepository
from app.ticketing.services.inbox_service import InboxService
from tests.test_bulk_mail_action_db import (
    NOT_AVAILABLE,
    _am,
    _by_id,
    _run,
    db_session,  # noqa: F401  (fixture)
)
from tests.test_mail_otp_section import _make_client, _make_email


def _service(session):
    return InboxService(
        InteractionRepository(session),
        message_mark_repository=MessageMarkRepository(session),
    )


async def _inbox(service, user, client):
    res = await service.get_inbox(user, client_id=client.client_id, view="pending")
    return res.items


async def test_flag_and_pin_are_personal_and_pinned_mail_sorts_first(db_session):
    me = await _am(db_session, "Marker")
    colleague = await _am(db_session, "Colleague")
    client = await _make_client(db_session, account_manager_id=me.user_id, label="A")
    older = await _make_email(db_session, is_otp=False, client_id=client.client_id)
    newer = await _make_email(db_session, is_otp=False, client_id=client.client_id)
    service = _service(db_session)

    # Newest first by default; nothing marked yet.
    items = await _inbox(service, me, client)
    assert [i.interaction_id for i in items] == [newer.interaction_id, older.interaction_id]
    assert not any(i.is_flagged or i.is_pinned for i in items)

    out = await _run(db_session, me, [older.interaction_id], "pin")
    assert out.succeeded == 1
    out = await _run(db_session, me, [older.interaction_id], "flag")
    assert out.succeeded == 1

    items = await _inbox(service, me, client)
    assert items[0].interaction_id == older.interaction_id  # pinned floats up
    assert items[0].is_pinned and items[0].is_flagged
    assert not items[1].is_pinned and not items[1].is_flagged

    # Personal: another user's view of the same mail is unmarked.
    marks = await MessageMarkRepository(db_session).get_marks(
        colleague.user_id, [older.interaction_id]
    )
    assert marks == {}

    # Un-marking both leaves no stray row, and the order reverts.
    await _run(db_session, me, [older.interaction_id], "unpin")
    await _run(db_session, me, [older.interaction_id], "unflag")
    rows = (
        await db_session.execute(
            select(MessageMark).where(MessageMark.user_id == me.user_id)
        )
    ).scalars().all()
    assert rows == []
    items = await _inbox(service, me, client)
    assert items[0].interaction_id == newer.interaction_id


async def test_cannot_mark_mail_the_caller_cannot_view(db_session):
    owner = await _am(db_session, "Owner2")
    stranger = await _am(db_session, "Stranger2")
    client = await _make_client(db_session, account_manager_id=owner.user_id, label="A")
    mail = await _make_email(db_session, is_otp=False, client_id=client.client_id)

    out = await _run(db_session, stranger, [mail.interaction_id], "flag")
    res = _by_id(out)[mail.interaction_id]
    assert res.status == "failed" and res.reason == NOT_AVAILABLE
    rows = (
        await db_session.execute(
            select(MessageMark).where(MessageMark.interaction_id == mail.interaction_id)
        )
    ).scalars().all()
    assert rows == []
