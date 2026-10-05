# test_message_marks_behavior_db.py
#
# Real-DB (rolled-back) coverage of the per-user Flag / Pin behaviour
# beyond the basics in test_message_marks_db.py: the Flagged filter,
# idempotency, Flag/Pin independence, "marks never mutate the mail",
# partial authorization, lifecycle (archive / OTP) and no per-row
# user-state queries. Same prerequisites as test_message_marks_db.py.

from sqlalchemy import event, func, select

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


async def _ids(service, user, client, **kw):
    kw.setdefault("view", "pending")
    res = await service.get_inbox(user, client_id=client.client_id, **kw)
    return [i.interaction_id for i in res.items]


async def _row_count(session, user, interaction):
    return (
        await session.execute(
            select(func.count())
            .select_from(MessageMark)
            .where(
                MessageMark.user_id == user.user_id,
                MessageMark.interaction_id == interaction.interaction_id,
            )
        )
    ).scalar_one()


async def test_flagged_filter_is_the_callers_own_flags_only(db_session):
    me = await _am(db_session, "FlagMe")
    other = await _am(db_session, "FlagOther")
    client = await _make_client(db_session, account_manager_id=me.user_id, label="A")
    a = await _make_email(db_session, is_otp=False, client_id=client.client_id)
    b = await _make_email(db_session, is_otp=False, client_id=client.client_id)
    c = await _make_email(db_session, is_otp=False, client_id=client.client_id)
    service = _service(db_session)

    await _run(db_session, me, [a.interaction_id, b.interaction_id], "flag")
    # Another user's flag on C (written directly) must never leak in.
    await MessageMarkRepository(db_session).set_flag(other.user_id, c.interaction_id, True)

    flagged = await _ids(service, me, client, flagged_only=True)
    assert set(flagged) == {a.interaction_id, b.interaction_id}
    # Unfiltered list is unchanged by the filter existing.
    assert len(await _ids(service, me, client)) == 3

    await _run(db_session, me, [a.interaction_id], "unflag")
    assert await _ids(service, me, client, flagged_only=True) == [b.interaction_id]


async def test_flag_and_pin_are_idempotent_and_independent(db_session):
    me = await _am(db_session, "Indep")
    client = await _make_client(db_session, account_manager_id=me.user_id, label="A")
    mail = await _make_email(db_session, is_otp=False, client_id=client.client_id)
    service = _service(db_session)
    mid = [mail.interaction_id]

    for _ in range(2):
        assert (await _run(db_session, me, mid, "flag")).succeeded == 1
        assert (await _run(db_session, me, mid, "pin")).succeeded == 1
    assert await _row_count(db_session, me, mail) == 1

    marks = await MessageMarkRepository(db_session).get_marks(me.user_id, mid)
    assert marks[mail.interaction_id] == (True, True)

    # Unflag does not unpin; unpin does not unflag.
    await _run(db_session, me, mid, "unflag")
    assert (await MessageMarkRepository(db_session).get_marks(me.user_id, mid))[
        mail.interaction_id
    ] == (False, True)
    await _run(db_session, me, mid, "flag")
    await _run(db_session, me, mid, "unpin")
    assert (await MessageMarkRepository(db_session).get_marks(me.user_id, mid))[
        mail.interaction_id
    ] == (True, False)

    # Duplicate un-marks are safe and leave no row behind.
    for _ in range(2):
        await _run(db_session, me, mid, "unflag")
        await _run(db_session, me, mid, "unpin")
    assert await _row_count(db_session, me, mail) == 0
    assert (await _run(db_session, me, mid, "unpin")).succeeded == 1
    assert mail.interaction_id in await _ids(service, me, client)


async def test_marks_never_mutate_the_mail(db_session):
    me = await _am(db_session, "Immutable")
    client = await _make_client(db_session, account_manager_id=me.user_id, label="A")
    mail = await _make_email(db_session, is_otp=False, client_id=client.client_id)
    before = (mail.received_at, mail.folder_id, mail.client_id, mail.ticket_id, mail.status)

    await _run(db_session, me, [mail.interaction_id], "flag")
    await _run(db_session, me, [mail.interaction_id], "pin")
    await db_session.refresh(mail)

    after = (mail.received_at, mail.folder_id, mail.client_id, mail.ticket_id, mail.status)
    assert after == before


async def test_bulk_partial_authorization_marks_only_visible_mail(db_session):
    me = await _am(db_session, "BulkMe")
    stranger = await _am(db_session, "BulkStranger")
    mine = await _make_client(db_session, account_manager_id=me.user_id, label="A")
    theirs = await _make_client(db_session, account_manager_id=stranger.user_id, label="B")
    ok = await _make_email(db_session, is_otp=False, client_id=mine.client_id)
    denied = await _make_email(db_session, is_otp=False, client_id=theirs.client_id)

    for action in ("flag", "pin"):
        out = await _run(db_session, me, [ok.interaction_id, denied.interaction_id], action)
        by_id = _by_id(out)
        assert by_id[ok.interaction_id].status == "success"
        assert by_id[denied.interaction_id].status == "failed"
        assert by_id[denied.interaction_id].reason == NOT_AVAILABLE
    assert await _row_count(db_session, me, denied) == 0


async def test_pinned_mail_leaves_pending_when_archived_but_keeps_its_mark(db_session):
    me = await _am(db_session, "Lifecycle")
    client = await _make_client(db_session, account_manager_id=me.user_id, label="A")
    mail = await _make_email(db_session, is_otp=False, client_id=client.client_id)
    other = await _make_email(db_session, is_otp=False, client_id=client.client_id)
    service = _service(db_session)

    await _run(db_session, me, [mail.interaction_id], "pin")
    assert (await _ids(service, me, client))[0] == mail.interaction_id

    out = await _run(db_session, me, [mail.interaction_id], "archive")
    assert out.succeeded == 1
    assert await _ids(service, me, client) == [other.interaction_id]
    # The user's preference is preserved, not deleted by the lifecycle change.
    assert await _row_count(db_session, me, mail) == 1


async def test_pin_and_flag_work_in_the_otp_view(db_session):
    me = await _am(db_session, "OtpMarker")
    client = await _make_client(db_session, account_manager_id=me.user_id, label="A")
    older = await _make_email(db_session, is_otp=True, client_id=client.client_id)
    newer = await _make_email(db_session, is_otp=True, client_id=client.client_id)
    service = _service(db_session)

    assert await _ids(service, me, client, view="otp") == [
        newer.interaction_id,
        older.interaction_id,
    ]
    await _run(db_session, me, [older.interaction_id], "pin")
    await _run(db_session, me, [older.interaction_id], "flag")
    assert (await _ids(service, me, client, view="otp"))[0] == older.interaction_id
    assert await _ids(service, me, client, view="otp", flagged_only=True) == [
        older.interaction_id
    ]
    # OTP visibility is unchanged: still not in the normal Inbox.
    assert older.interaction_id not in await _ids(service, me, client)


async def test_inbox_user_state_costs_a_constant_number_of_queries(db_session):
    me = await _am(db_session, "Perf")
    client = await _make_client(db_session, account_manager_id=me.user_id, label="A")
    service = _service(db_session)
    bind = db_session.get_bind()

    async def count_queries():
        n = 0

        def hook(*_args, **_kwargs):
            nonlocal n
            n += 1

        event.listen(bind, "before_cursor_execute", hook)
        try:
            await _ids(service, me, client)
        finally:
            event.remove(bind, "before_cursor_execute", hook)
        return n

    first = await _make_email(db_session, is_otp=False, client_id=client.client_id)
    await _run(db_session, me, [first.interaction_id], "pin")
    one_row = await count_queries()

    extra = []
    for _ in range(5):
        m = await _make_email(db_session, is_otp=False, client_id=client.client_id)
        extra.append(m.interaction_id)
    await _run(db_session, me, extra, "flag")
    many_rows = await count_queries()

    assert many_rows == one_row


async def test_flagged_view_spans_states_excludes_trash_and_counts_own_flags(db_session):
    me = await _am(db_session, "FlagView")
    other = await _am(db_session, "FlagViewOther")
    client = await _make_client(db_session, account_manager_id=me.user_id, label="A")
    pending = await _make_email(db_session, is_otp=False, client_id=client.client_id)
    otp = await _make_email(db_session, is_otp=True, client_id=client.client_id)
    archived = await _make_email(db_session, is_otp=False, client_id=client.client_id)
    plain = await _make_email(db_session, is_otp=False, client_id=client.client_id)
    trashed = await _make_email(db_session, is_otp=False, client_id=client.client_id)
    service = _service(db_session)

    ids = [pending.interaction_id, otp.interaction_id, archived.interaction_id, trashed.interaction_id]
    await _run(db_session, me, ids, "flag")
    await _run(db_session, me, [archived.interaction_id], "archive")
    await _run(db_session, me, [trashed.interaction_id], "delete")
    await MessageMarkRepository(db_session).set_flag(other.user_id, plain.interaction_id, True)

    flagged = await _ids(service, me, client, view="flagged")
    assert set(flagged) == {pending.interaction_id, otp.interaction_id, archived.interaction_id}

    counts = await service.get_view_counts(me, client_id=client.client_id)
    assert counts["flagged"] == 3
