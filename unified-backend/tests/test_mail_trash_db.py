# test_mail_trash_db.py
#
# Real-DB (rolled-back) coverage of the Mail "Trash" section: a bulk
# "delete" moves a root into view=trash (and out of every other view and
# count), "restore" brings it back, and authorization is the same as
# delete's. Same prerequisites as test_bulk_mail_action_db.py: a throwaway
# database migrated to head (including INTERACTION_RESTORED), never the
# shared RDS. Run this file on its own.

from sqlalchemy import select

from app.ticketing.models.audit_log import AuditLog
from app.ticketing.repositories.interaction_repository import InteractionRepository
from app.ticketing.services.inbox_service import InboxService
from tests.test_bulk_mail_action_db import (
    NOT_AVAILABLE,
    _am,
    _by_id,
    _run,
    db_session,  # noqa: F401  (fixture)
)
from tests.test_mail_otp_section import _make_client, _make_email


async def test_delete_moves_to_trash_and_restore_brings_it_back(db_session):
    user = await _am(db_session, "Trasher")
    client = await _make_client(db_session, account_manager_id=user.user_id, label="A")
    keep = await _make_email(db_session, is_otp=False, client_id=client.client_id)
    gone = await _make_email(db_session, is_otp=False, client_id=client.client_id)

    service = InboxService(InteractionRepository(db_session))

    out = await _run(db_session, user, [gone.interaction_id], "delete")
    assert out.succeeded == 1

    trash = await service.get_inbox(user, client_id=client.client_id, view="trash")
    assert [i.interaction_id for i in trash.items] == [gone.interaction_id]
    for view in ("pending", "all"):
        res = await service.get_inbox(user, client_id=client.client_id, view=view)
        assert gone.interaction_id not in {i.interaction_id for i in res.items}
        assert keep.interaction_id in {i.interaction_id for i in res.items}

    counts = await service.get_view_counts(user, client_id=client.client_id)
    assert counts["trash"] == 1 and counts["pending"] == 1 and counts["all"] == 1

    out = await _run(db_session, user, [gone.interaction_id], "restore")
    assert out.succeeded == 1
    trash = await service.get_inbox(user, client_id=client.client_id, view="trash")
    assert trash.items == []
    counts = await service.get_view_counts(user, client_id=client.client_id)
    assert counts["trash"] == 0 and counts["pending"] == 2

    events = (
        await db_session.execute(
            select(AuditLog.event_type).where(AuditLog.entity_id == gone.interaction_id)
        )
    ).scalars().all()
    assert {e.value for e in events} >= {"INTERACTION_HIDDEN", "INTERACTION_RESTORED"}


async def test_restore_of_a_visible_message_is_rejected(db_session):
    user = await _am(db_session, "Trasher2")
    client = await _make_client(db_session, account_manager_id=user.user_id, label="A")
    mail = await _make_email(db_session, is_otp=False, client_id=client.client_id)

    out = await _run(db_session, user, [mail.interaction_id], "restore")
    assert out.failed == 1


async def test_other_accounts_trash_is_invisible_and_not_restorable(db_session):
    owner = await _am(db_session, "Owner")
    stranger = await _am(db_session, "Stranger")
    client = await _make_client(db_session, account_manager_id=owner.user_id, label="A")
    mail = await _make_email(db_session, is_otp=False, client_id=client.client_id)
    await _run(db_session, owner, [mail.interaction_id], "delete")

    service = InboxService(InteractionRepository(db_session))
    seen = await service.get_inbox(stranger, view="trash")
    assert mail.interaction_id not in {i.interaction_id for i in seen.items}

    out = await _run(db_session, stranger, [mail.interaction_id], "restore")
    res = _by_id(out)[mail.interaction_id]
    assert res.status == "failed" and res.reason == NOT_AVAILABLE
