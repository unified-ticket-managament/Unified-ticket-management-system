# test_bulk_mail_action_db.py
#
# Real-DB (rolled-back) coverage of POST /inbox/bulk-action's service with
# the REAL existing services behind it: per-interaction authorization,
# partial success, Category Account Manager OTP scope, folder
# authorization, one ticket per email, attach/reopen, and read counts.
#
# Same prerequisites as test_mail_otp_section.py: a database migrated to
# head, DATABASE_URL pointed at a throwaway database (never the shared
# RDS), seeded roles. Run this file on its own.

import uuid

import pytest
from sqlalchemy import select
from shared_models.models import Category

from app.database.session import AsyncSessionLocal, engine
from app.ticketing.enums import InteractionStatus, TicketStatus
from app.ticketing.models.interaction import Interaction
from app.ticketing.models.mail_folder import MailFolder
from app.ticketing.models.ticket import Ticket
from app.ticketing.repositories.interaction_repository import InteractionRepository
from app.ticketing.repositories.message_read_receipt_repository import (
    MessageReadReceiptRepository,
)
from app.ticketing.schemas.bulk_mail_action import BulkMailActionRequest
from app.ticketing.services.bulk_mail_action_service import (
    NOT_AVAILABLE,
    FOLDER_NOT_AVAILABLE,
    build_bulk_mail_action_service,
)
from app.ticketing.services.inbox_service import InboxService
from tests.test_mail_otp_section import (
    _assign_category,
    _make_category,
    _make_client,
    _make_email,
    _make_user,
)

AM_PERMISSIONS = [
    "communication:view_assigned",
    "communication:archive",
    "communication:move_to_folder",
    "communication:reply_external",
    "communication:attach_to_ticket",
    "ticket:create",
    "ticket:reopen",
    "ticket:update_status",
]


@pytest.fixture
async def db_session():
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.rollback()
    await engine.dispose()


async def _am(session, label):
    return await _make_user(session, "Account Manager", label, list(AM_PERMISSIONS))


def _req(ids, action, **kw):
    return BulkMailActionRequest(interaction_ids=ids, action=action, **kw)


async def _run(session, user, ids, action, **kw):
    service = build_bulk_mail_action_service(session)
    return await service.run(_req(ids, action, **kw), user)


def _by_id(result):
    return {r.interaction_id: r for r in result.results}


async def _status(session, interaction):
    await session.refresh(interaction)
    return interaction.status


# ---------------------------------------------------------------------
# Archive — mixed authorized / unauthorized
# ---------------------------------------------------------------------


async def test_archive_mixed_selection_is_partial_success(db_session):
    satish = await _am(db_session, "Satish")
    other = await _am(db_session, "Other")
    mine_client = await _make_client(db_session, account_manager_id=satish.user_id, label="A")
    mine_client2 = await _make_client(db_session, account_manager_id=satish.user_id, label="B")
    theirs = await _make_client(db_session, account_manager_id=other.user_id, label="C")

    a = await _make_email(db_session, is_otp=False, client_id=mine_client.client_id)
    b = await _make_email(db_session, is_otp=False, client_id=mine_client2.client_id)
    c = await _make_email(db_session, is_otp=False, client_id=theirs.client_id)

    out = await _run(db_session, satish, [a.interaction_id, b.interaction_id, c.interaction_id], "archive")

    assert (out.requested, out.succeeded, out.failed) == (3, 2, 1)
    res = _by_id(out)
    assert res[a.interaction_id].status == res[b.interaction_id].status == "success"
    assert res[c.interaction_id].status == "failed"
    assert res[c.interaction_id].reason == NOT_AVAILABLE
    assert await _status(db_session, a) == InteractionStatus.IGNORED
    assert await _status(db_session, b) == InteractionStatus.IGNORED
    # The unauthorized interaction was NOT modified.
    assert await _status(db_session, c) == InteractionStatus.PENDING


async def test_archive_without_permission_modifies_nothing(db_session):
    user = await _make_user(
        db_session, "Account Manager", "NoPerm", ["communication:view_assigned"]
    )
    client = await _make_client(db_session, account_manager_id=user.user_id, label="A")
    mail = await _make_email(db_session, is_otp=False, client_id=client.client_id)

    out = await _run(db_session, user, [mail.interaction_id], "archive")
    assert out.failed == 1
    assert await _status(db_session, mail) == InteractionStatus.PENDING


# ---------------------------------------------------------------------
# Mark read / unread — authorization + counts
# ---------------------------------------------------------------------


async def test_mark_read_and_unread_respect_visibility_and_update_counts(db_session):
    satish = await _am(db_session, "Satish")
    other = await _am(db_session, "Other")
    client = await _make_client(db_session, account_manager_id=satish.user_id, label="A")
    foreign = await _make_client(db_session, account_manager_id=other.user_id, label="B")

    otps = [await _make_email(db_session, is_otp=True, client_id=client.client_id) for _ in range(2)]
    inbox = [await _make_email(db_session, is_otp=False, client_id=client.client_id) for _ in range(2)]
    hidden = await _make_email(db_session, is_otp=False, client_id=foreign.client_id)
    ids = [m.interaction_id for m in (*otps, *inbox, hidden)]

    out = await _run(db_session, satish, ids, "mark_read")
    assert (out.succeeded, out.failed) == (4, 1)
    assert _by_id(out)[hidden.interaction_id].status == "failed"

    # No receipt was written for the mail the caller can't see.
    read_ids = await MessageReadReceiptRepository(db_session).get_read_interaction_ids(
        satish.user_id, ids
    )
    assert hidden.interaction_id not in read_ids
    assert {m.interaction_id for m in (*otps, *inbox)} <= set(read_ids)

    service = InboxService(InteractionRepository(db_session))
    counts = await service.get_view_counts(satish, client_id=client.client_id)
    assert counts["otp"] == 2 and counts["otp_unread"] == 0
    assert counts["pending"] == 2  # OTPs stay out of the Inbox count

    # Mark only the OTPs unread: OTP unread goes back up, Inbox untouched.
    out = await _run(db_session, satish, [m.interaction_id for m in otps], "mark_unread")
    assert out.succeeded == 2
    counts = await service.get_view_counts(satish, client_id=client.client_id)
    assert counts["otp_unread"] == 2
    read_ids = await MessageReadReceiptRepository(db_session).get_read_interaction_ids(
        satish.user_id, [m.interaction_id for m in inbox]
    )
    assert {m.interaction_id for m in inbox} <= set(read_ids)


# ---------------------------------------------------------------------
# Category Account Manager — OTP scope stays category-scoped
# ---------------------------------------------------------------------


async def test_category_account_manager_bulk_scope_follows_category_not_org(db_session):
    koushik = await _am(db_session, "Koushik")
    category_x = await _make_category(db_session, "X")
    category_y = await _make_category(db_session, "Y")
    await _assign_category(
        db_session, account_manager_id=koushik.user_id, category_id=category_x.category_id
    )

    otps_x = [
        await _make_email(
            db_session,
            is_otp=True,
            category_id=category_x.category_id,
            from_email=f"no-reply@client-{label}.example.com",
        )
        for label in ("a", "b", "c")
    ]
    otp_y = await _make_email(db_session, is_otp=True, category_id=category_y.category_id)
    ids = [m.interaction_id for m in (*otps_x, otp_y)]

    # Read: every OTP in the managed category (across clients) works;
    # the other category's OTP does not.
    out = await _run(db_session, koushik, ids, "mark_read")
    res = _by_id(out)
    assert all(res[m.interaction_id].status == "success" for m in otps_x)
    assert res[otp_y.interaction_id].status == "failed"

    # Write: archive is likewise scoped per interaction, not org-wide.
    out = await _run(db_session, koushik, ids, "archive")
    assert (out.succeeded, out.failed) == (3, 1)
    assert await _status(db_session, otp_y) == InteractionStatus.PENDING


# ---------------------------------------------------------------------
# Move — folder authorization
# ---------------------------------------------------------------------


async def _make_folder(session, owner, label):
    folder = MailFolder(
        folder_id=uuid.uuid4(),
        name=f"Bulk Test {label} {uuid.uuid4().hex[:8]}",
        created_by=owner.user_id,
    )
    session.add(folder)
    await session.flush()
    return folder


async def test_move_to_own_folder_succeeds_and_unauthorized_folder_is_rejected(db_session):
    satish = await _am(db_session, "Satish")
    other = await _am(db_session, "Other")
    client = await _make_client(db_session, account_manager_id=satish.user_id, label="A")
    mails = [await _make_email(db_session, is_otp=False, client_id=client.client_id) for _ in range(2)]
    ids = [m.interaction_id for m in mails]

    mine = await _make_folder(db_session, satish, "mine")
    out = await _run(db_session, satish, ids, "move", folder_id=mine.folder_id)
    assert out.succeeded == 2
    for m in mails:
        await db_session.refresh(m)
        assert m.folder_id == mine.folder_id

    theirs = await _make_folder(db_session, other, "theirs")
    out = await _run(db_session, satish, ids, "move", folder_id=theirs.folder_id)
    assert out.failed == 2
    assert {r.reason for r in out.results} == {FOLDER_NOT_AVAILABLE}
    for m in mails:
        await db_session.refresh(m)
        assert m.folder_id == mine.folder_id  # unchanged


# ---------------------------------------------------------------------
# Create ticket — one ticket per email, never merged
# ---------------------------------------------------------------------


async def _category_name(session):
    category = await _make_category(session, "Tk")
    return category.category_name


async def test_create_ticket_creates_one_ticket_per_email_across_clients(db_session):
    satish = await _am(db_session, "Satish")
    other = await _am(db_session, "Other")
    c1 = await _make_client(db_session, account_manager_id=satish.user_id, label="A")
    c2 = await _make_client(db_session, account_manager_id=satish.user_id, label="B")
    foreign = await _make_client(db_session, account_manager_id=other.user_id, label="C")
    m1 = await _make_email(db_session, is_otp=False, client_id=c1.client_id, subject="Invoice A")
    m2 = await _make_email(db_session, is_otp=False, client_id=c2.client_id, subject="Outage B")
    m3 = await _make_email(db_session, is_otp=False, client_id=foreign.client_id, subject="Not mine")

    out = await _run(
        db_session,
        satish,
        [m1.interaction_id, m2.interaction_id, m3.interaction_id],
        "create_ticket",
        ticket_type=await _category_name(db_session),
    )

    res = _by_id(out)
    assert res[m1.interaction_id].status == res[m2.interaction_id].status == "success"
    assert res[m3.interaction_id].status == "failed"
    t1, t2 = res[m1.interaction_id].ticket_id, res[m2.interaction_id].ticket_id
    assert t1 and t2 and t1 != t2  # never merged

    tickets = {
        t.ticket_id: t
        for t in (
            await db_session.execute(select(Ticket).where(Ticket.ticket_id.in_([t1, t2])))
        ).scalars()
    }
    assert tickets[t1].title == "Invoice A"
    assert tickets[t2].title == "Outage B"
    assert tickets[t1].client_company_id != tickets[t2].client_company_id
    await db_session.refresh(m1)
    await db_session.refresh(m3)
    assert m1.ticket_id == t1
    assert m3.ticket_id is None  # unauthorized interaction untouched


# ---------------------------------------------------------------------
# Attach — closed ticket reopens through the EXISTING workflow
# ---------------------------------------------------------------------


async def _make_ticket(session, *, client, creator, status, title="Existing"):
    ticket = Ticket(
        ticket_id=uuid.uuid4(),
        client_id=None,
        client_company_id=client.client_id,
        agent_id=creator.user_id,
        created_by=creator.user_id,
        title=title,
        ticket_type=await _category_name(session),
        current_status=status,
        ticket_number=int(uuid.uuid4().int % 10**9) + 10**7,
        ticket_number_series="legacy",
    )
    session.add(ticket)
    await session.flush()
    return ticket


async def test_attach_to_open_ticket_partial_success_and_unauthorized_ticket(db_session):
    satish = await _am(db_session, "Satish")
    other = await _am(db_session, "Other")
    client = await _make_client(db_session, account_manager_id=satish.user_id, label="A")
    foreign = await _make_client(db_session, account_manager_id=other.user_id, label="B")
    ticket = await _make_ticket(db_session, client=client, creator=satish, status=TicketStatus.OPEN)
    foreign_ticket = await _make_ticket(
        db_session, client=foreign, creator=other, status=TicketStatus.OPEN
    )

    mine = [await _make_email(db_session, is_otp=False, client_id=client.client_id) for _ in range(2)]
    theirs = await _make_email(db_session, is_otp=False, client_id=foreign.client_id)
    ids = [m.interaction_id for m in (*mine, theirs)]

    out = await _run(db_session, satish, ids, "attach_to_ticket", ticket_id=ticket.ticket_id)
    res = _by_id(out)
    assert all(res[m.interaction_id].status == "success" for m in mine)
    assert res[theirs.interaction_id].status == "failed"
    await db_session.refresh(theirs)
    assert theirs.ticket_id is None

    # An unauthorized TICKET cannot be attached to at all.
    again = await _make_email(db_session, is_otp=False, client_id=client.client_id)
    out = await _run(
        db_session, satish, [again.interaction_id], "link_ticket", ticket_id=foreign_ticket.ticket_id
    )
    assert out.failed == 1
    await db_session.refresh(again)
    assert again.ticket_id is None


async def test_attach_to_closed_ticket_reopens_it_keeping_id_and_history(db_session):
    satish = await _am(db_session, "Satish")
    client = await _make_client(db_session, account_manager_id=satish.user_id, label="A")
    ticket = await _make_ticket(
        db_session, client=client, creator=satish, status=TicketStatus.CLOSED
    )
    original_id, original_number = ticket.ticket_id, ticket.ticket_number
    mails = [await _make_email(db_session, is_otp=False, client_id=client.client_id) for _ in range(2)]

    out = await _run(
        db_session, satish, [m.interaction_id for m in mails], "attach_to_ticket",
        ticket_id=ticket.ticket_id,
    )

    assert out.succeeded == 2, [r.reason for r in out.results]
    await db_session.refresh(ticket)
    # Same existing reopening rule as the single workflow: CLOSED -> IN_PROGRESS.
    assert ticket.current_status == TicketStatus.IN_PROGRESS
    assert ticket.ticket_id == original_id and ticket.ticket_number == original_number
    for m in mails:
        await db_session.refresh(m)
        assert m.ticket_id == original_id


async def test_attach_to_closed_ticket_without_reopen_permission_rolls_the_item_back(db_session):
    # The reopen path demands ticket:update_status — an existing rule the
    # bulk call inherits. A caller without it must leave BOTH the ticket
    # (still CLOSED) and the interaction (still unattached) untouched:
    # the failed item's savepoint rolls back everything it did.
    limited = await _make_user(
        db_session,
        "Account Manager",
        "Limited",
        [p for p in AM_PERMISSIONS if p != "ticket:update_status"],
    )
    client = await _make_client(db_session, account_manager_id=limited.user_id, label="A")
    ticket = await _make_ticket(
        db_session, client=client, creator=limited, status=TicketStatus.CLOSED
    )
    mail = await _make_email(db_session, is_otp=False, client_id=client.client_id)

    out = await _run(
        db_session, limited, [mail.interaction_id], "attach_to_ticket", ticket_id=ticket.ticket_id
    )

    assert out.failed == 1
    await db_session.refresh(ticket)
    await db_session.refresh(mail)
    assert ticket.current_status == TicketStatus.CLOSED
    assert mail.ticket_id is None


async def test_attach_never_crosses_clients_even_when_the_caller_owns_both(db_session):
    # The caller is the Account Manager of BOTH clients, so ownership
    # alone would allow it — the per-interaction client check must still
    # keep client B's mail off client A's ticket.
    satish = await _am(db_session, "Satish")
    client_a = await _make_client(db_session, account_manager_id=satish.user_id, label="A")
    client_b = await _make_client(db_session, account_manager_id=satish.user_id, label="B")
    ticket = await _make_ticket(db_session, client=client_a, creator=satish, status=TicketStatus.OPEN)
    mail_a = await _make_email(db_session, is_otp=False, client_id=client_a.client_id)
    mail_b = await _make_email(db_session, is_otp=False, client_id=client_b.client_id)

    out = await _run(
        db_session,
        satish,
        [mail_a.interaction_id, mail_b.interaction_id],
        "link_ticket",
        ticket_id=ticket.ticket_id,
    )

    res = _by_id(out)
    assert res[mail_a.interaction_id].status == "success"
    assert res[mail_b.interaction_id].status == "failed"
    await db_session.refresh(mail_b)
    assert mail_b.ticket_id is None
