# test_mail_otp_section.py
#
# Coverage for the Mail "OTPs" section:
# - Ingestion (no DB, fake repositories): EmailService.receive_email
#   persists the EXISTING classifier's result (otp_classifier.
#   classify_otp_email) on the new Interaction as is_otp, calls it
#   once, and never logs the code itself.
# - Queries (real DB, rolled-back transaction — same convention as
#   test_inbox_folder_exclusion.py): list_inbox's "otp" view vs the
#   Inbox ("pending"/"replied") views, client and category Account
#   Manager scope, search, pagination, unread counts and direct
#   open-by-id authorization.
#
# The DB half needs a database migrated to head (is_otp column). Point
# DATABASE_URL at a throwaway database — every DB test here rolls back,
# but it still reads/writes real tables.

import logging
import uuid
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import joinedload
from shared_models.models import Category, Role, User

from app.database.session import AsyncSessionLocal, engine
from app.rbac.models.reporting_manager_team import ReportingManagerTeam
from app.ticketing.enums import InteractionDirection, InteractionStatus
from app.ticketing.models.client import Client
from app.ticketing.models.interaction import Interaction
from app.ticketing.repositories.client_repository import ClientRepository
from app.ticketing.repositories.distribution_list_repository import DistributionListRepository
from app.ticketing.repositories.interaction_repository import InteractionRepository
from app.ticketing.repositories.mail_folder_repository import MailFolderRepository
from app.ticketing.repositories.message_read_receipt_repository import (
    MessageReadReceiptRepository,
)
from app.ticketing.repositories.rule_repository import RuleRepository
from app.ticketing.services import otp_classifier
from app.ticketing.services.inbox_service import InboxService
from app.ticketing.services.open_email_service import OpenEmailService
from tests.test_email_service_otp_sla_completion import (
    _FakeInteractionRepository,
    _FakeRuleEngineService,
    _FakeSLAService,
    _GENUINE_OTP_EMAIL,
    _build_service,
    _email_request,
)

_OTP_CODE = "482931"


# ---------------------------------------------------------------------
# Ingestion — no DB
# ---------------------------------------------------------------------


class _RecordingInteractionRepository(_FakeInteractionRepository):
    """Records every InteractionCreate and rejects a repeated message_id."""

    def __init__(self):
        super().__init__()
        self.created = []

    async def exists_by_message_id(self, message_id):
        return any(c.message_id == message_id for c in self.created)

    async def create(self, interaction_create):
        self.created.append(interaction_create)
        return await super().create(interaction_create)


def _build_recording_service(monkeypatch, **kwargs):
    service = _build_service(monkeypatch, **kwargs)
    service.interaction_repository = _RecordingInteractionRepository()
    return service


def _spy_on_classifier(monkeypatch):
    calls = []
    real = otp_classifier.classify_otp_email

    def spy(subject, body, *, threshold):
        result = real(subject, body, threshold=threshold)
        calls.append({"subject": subject, "body": body, "threshold": threshold, "result": result})
        return result

    monkeypatch.setattr("app.ticketing.services.email_service.classify_otp_email", spy)
    return calls


async def test_normal_email_is_persisted_as_not_otp(monkeypatch):
    service = _build_recording_service(monkeypatch)

    await service.receive_email(_email_request())

    assert service.interaction_repository.created[0].is_otp is False


async def test_otp_email_is_persisted_as_otp_using_existing_classifier(monkeypatch):
    calls = _spy_on_classifier(monkeypatch)
    call_log = []
    rule_engine = _FakeRuleEngineService(call_log)
    sla_service = _FakeSLAService()
    service = _build_recording_service(
        monkeypatch, sla_service=sla_service, rule_engine_service=rule_engine
    )

    await service.receive_email(_email_request(**_GENUINE_OTP_EMAIL))

    # The existing classifier ran exactly once, on the email's own
    # subject/body at the configured threshold...
    assert len(calls) == 1
    assert calls[0]["subject"] == _GENUINE_OTP_EMAIL["subject"]
    assert calls[0]["body"] == _GENUINE_OTP_EMAIL["body"]
    assert calls[0]["threshold"] == 0.90
    assert calls[0]["result"].is_otp is True
    # ...its result is what got persisted...
    assert service.interaction_repository.created[0].is_otp is True
    # ...and the same result still drives SLA completion and the rules.
    assert sla_service.completed_calls[0]["completion_reason"] == "OTP_RECOGNIZED"
    assert rule_engine.last_context.otp_detected is True


async def test_persisted_flag_follows_classifier_result_not_keywords(monkeypatch):
    service = _build_recording_service(monkeypatch)

    await service.receive_email(
        _email_request(
            subject="Unable to receive OTP",
            body="The customer is unable to receive the OTP. Please investigate.",
        )
    )

    assert service.interaction_repository.created[0].is_otp is False


async def test_duplicate_graph_ingestion_creates_one_otp_row(monkeypatch):
    service = _build_recording_service(monkeypatch)
    request = _email_request(**_GENUINE_OTP_EMAIL)

    await service.receive_email(request)
    with pytest.raises(ValueError, match="already processed"):
        await service.receive_email(request)

    assert len(service.interaction_repository.created) == 1


async def test_otp_code_is_never_logged(monkeypatch, caplog):
    service = _build_recording_service(monkeypatch)

    with caplog.at_level(logging.DEBUG):
        await service.receive_email(_email_request(**_GENUINE_OTP_EMAIL))

    assert _OTP_CODE not in caplog.text


# ---------------------------------------------------------------------
# Queries — real DB, rolled back
# ---------------------------------------------------------------------


@pytest.fixture
async def db_session():
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.rollback()
    await engine.dispose()


async def _role(session, name) -> Role:
    role = (await session.execute(select(Role).where(Role.name == name))).scalars().first()
    if role is None:
        pytest.skip(f"Role {name!r} is not seeded.")
    return role


async def _make_user(session, role_name, label, permissions) -> User:
    role = await _role(session, role_name)
    user = User(
        user_id=uuid.uuid4(),
        name=f"OTP Test {label}",
        email=f"otp-test-{label.lower()}-{uuid.uuid4().hex[:8]}@example.com",
        password_hash="x",
        role_id=role.role_id,
        is_active=True,
    )
    session.add(user)
    await session.flush()
    user = (
        await session.execute(
            select(User).options(joinedload(User.role)).where(User.user_id == user.user_id)
        )
    ).unique().scalar_one()
    # Transient, JWT-derived in production (see access_control.has_permission).
    user.permissions = permissions
    return user


async def _make_account_manager(session, label) -> User:
    return await _make_user(
        session, "Account Manager", label, ["communication:view_assigned"]
    )


async def _make_super_admin(session) -> User:
    return await _make_user(
        session, "Super Admin", "Admin", ["communication:view_all", "communication:view_assigned"]
    )


async def _make_client(session, *, account_manager_id, label) -> Client:
    client = Client(
        client_id=uuid.uuid4(),
        name=f"OTP Test Client {label}",
        inbox_email=f"otp-test-client-{label.lower()}-{uuid.uuid4().hex[:8]}@example.com",
        account_manager_id=account_manager_id,
        is_active=True,
    )
    session.add(client)
    await session.flush()
    return client


async def _make_category(session, label) -> Category:
    category = Category(category_name=f"OTP Test Category {label} {uuid.uuid4().hex[:8]}")
    session.add(category)
    await session.flush()
    return category


async def _assign_category(session, *, account_manager_id, category_id) -> None:
    session.add(
        ReportingManagerTeam(account_manager_id=account_manager_id, category_id=category_id)
    )
    await session.flush()


_received_offset = 0


async def _make_email(
    session,
    *,
    is_otp,
    client_id=None,
    category_id=None,
    subject=None,
    from_email="sender@example.com",
    parent_interaction_id=None,
    status=InteractionStatus.PENDING,
) -> Interaction:
    global _received_offset
    _received_offset += 1
    if subject is None:
        subject = "Your verification code" if is_otp else "Question about billing"
    interaction = Interaction(
        interaction_id=uuid.uuid4(),
        interaction_type="EMAIL",
        direction=InteractionDirection.INBOUND,
        status=status,
        payload={
            "subject": subject,
            "body": f"Your code is {_OTP_CODE}." if is_otp else "Hello.",
            "from_email": from_email,
            "to_email": "support@probeps.com",
            "client_name": "OTP Test",
        },
        parent_interaction_id=parent_interaction_id,
        client_id=client_id,
        category_id=category_id,
        is_visible=True,
        is_otp=is_otp,
        subject=subject,
        # Distinct, recent timestamps so these rows sort first and
        # pagination order is deterministic.
        received_at=datetime.now(timezone.utc) + timedelta(days=1, seconds=_received_offset),
    )
    session.add(interaction)
    await session.flush()
    return interaction


async def _inbox_ids(service, user, view, **kwargs) -> set:
    result = await service.get_inbox(user, view=view, **kwargs)
    return {item.interaction_id for item in result.items}


async def test_normal_email_in_inbox_only_and_otp_in_otps_only(db_session):
    admin = await _make_super_admin(db_session)
    normal = await _make_email(db_session, is_otp=False)
    otp = await _make_email(db_session, is_otp=True)
    service = InboxService(InteractionRepository(db_session))

    pending = await _inbox_ids(service, admin, "pending")
    otps = await _inbox_ids(service, admin, "otp")

    assert normal.interaction_id in pending
    assert normal.interaction_id not in otps
    assert otp.interaction_id in otps
    assert otp.interaction_id not in pending
    # Never in both, for any row in scope.
    assert not (pending & otps)


async def test_replied_otp_stays_out_of_inbox_views(db_session):
    admin = await _make_super_admin(db_session)
    replied_otp = await _make_email(db_session, is_otp=True, status=InteractionStatus.ASSIGNED)
    service = InboxService(InteractionRepository(db_session))

    assert replied_otp.interaction_id not in await _inbox_ids(service, admin, "replied")
    assert replied_otp.interaction_id in await _inbox_ids(service, admin, "otp")


async def test_otp_reply_does_not_move_its_normal_conversation(db_session):
    admin = await _make_super_admin(db_session)
    root = await _make_email(db_session, is_otp=False)
    otp_reply = await _make_email(
        db_session, is_otp=True, parent_interaction_id=root.interaction_id
    )
    service = InboxService(InteractionRepository(db_session))

    pending = await _inbox_ids(service, admin, "pending")
    otps = await _inbox_ids(service, admin, "otp")

    assert root.interaction_id in pending
    assert root.interaction_id not in otps
    # A reply is never a list row of its own — no duplicate anywhere.
    assert otp_reply.interaction_id not in pending | otps


async def test_client_account_manager_sees_only_own_clients_otps(db_session):
    satish = await _make_account_manager(db_session, "Satish")
    koushik = await _make_account_manager(db_session, "Koushik")
    client_a = await _make_client(db_session, account_manager_id=satish.user_id, label="A")
    client_b = await _make_client(db_session, account_manager_id=koushik.user_id, label="B")
    otp_a = await _make_email(db_session, is_otp=True, client_id=client_a.client_id)
    otp_b = await _make_email(db_session, is_otp=True, client_id=client_b.client_id)
    service = InboxService(InteractionRepository(db_session))

    satish_otps = await _inbox_ids(service, satish, "otp")
    koushik_otps = await _inbox_ids(service, koushik, "otp")

    assert otp_a.interaction_id in satish_otps
    assert otp_b.interaction_id not in satish_otps
    assert otp_b.interaction_id in koushik_otps
    assert otp_a.interaction_id not in koushik_otps
    # A client filter can't widen scope to someone else's client.
    assert otp_b.interaction_id not in await _inbox_ids(
        service, satish, "otp", client_id=client_b.client_id
    )


async def test_category_account_manager_sees_all_category_otps_across_clients(db_session):
    koushik = await _make_account_manager(db_session, "Koushik")
    satish = await _make_account_manager(db_session, "Satish")
    category_x = await _make_category(db_session, "X")
    category_y = await _make_category(db_session, "Y")
    await _assign_category(
        db_session, account_manager_id=koushik.user_id, category_id=category_x.category_id
    )

    # Category-mailbox mail carries no client_id (EmailService resolves
    # either a client mailbox or a category mailbox, never both), so
    # each client's OTP is told apart by its sender.
    otps_x = [
        await _make_email(
            db_session,
            is_otp=True,
            category_id=category_x.category_id,
            from_email=f"no-reply@client-{label}.example.com",
        )
        for label in ("a", "b", "c", "d")
    ]
    otp_y = await _make_email(db_session, is_otp=True, category_id=category_y.category_id)
    normal_x = await _make_email(db_session, is_otp=False, category_id=category_x.category_id)
    service = InboxService(InteractionRepository(db_session))

    koushik_otps = await _inbox_ids(service, koushik, "otp")
    koushik_pending = await _inbox_ids(service, koushik, "pending")

    assert {otp.interaction_id for otp in otps_x} <= koushik_otps
    assert otp_y.interaction_id not in koushik_otps
    assert normal_x.interaction_id in koushik_pending
    assert normal_x.interaction_id not in koushik_otps
    assert not ({otp.interaction_id for otp in otps_x} & koushik_pending)
    # Category filter narrows within his managed categories.
    assert {otp.interaction_id for otp in otps_x} <= await _inbox_ids(
        service, koushik, "otp", category_filter=category_x.category_name
    )
    assert not await _inbox_ids(
        service, koushik, "otp", category_filter=category_y.category_name
    )
    # An Account Manager who doesn't manage Category X sees none of them.
    assert not ({otp.interaction_id for otp in otps_x} & await _inbox_ids(service, satish, "otp"))


async def test_unread_counts_keep_otps_out_of_inbox(db_session):
    satish = await _make_account_manager(db_session, "Satish")
    client = await _make_client(db_session, account_manager_id=satish.user_id, label="A")
    for _ in range(3):
        await _make_email(db_session, is_otp=False, client_id=client.client_id)
    otps = [await _make_email(db_session, is_otp=True, client_id=client.client_id) for _ in range(2)]
    service = InboxService(InteractionRepository(db_session))

    counts = await service.get_view_counts(satish, client_id=client.client_id)
    assert counts["pending"] == 3
    assert counts["otp"] == 2
    assert counts["otp_unread"] == 2

    await MessageReadReceiptRepository(db_session).mark_read(
        satish.user_id, otps[0].interaction_id
    )

    counts = await service.get_view_counts(satish, client_id=client.client_id)
    assert counts["pending"] == 3
    assert counts["otp"] == 2
    assert counts["otp_unread"] == 1


async def test_search_respects_otp_separation(db_session):
    satish = await _make_account_manager(db_session, "Satish")
    client = await _make_client(db_session, account_manager_id=satish.user_id, label="A")
    tag = uuid.uuid4().hex[:8]
    otp = await _make_email(
        db_session, is_otp=True, client_id=client.client_id, subject=f"verification {tag}"
    )
    normal = await _make_email(
        db_session, is_otp=False, client_id=client.client_id, subject=f"verification {tag} help"
    )
    service = InboxService(InteractionRepository(db_session))

    assert await _inbox_ids(service, satish, "pending", search=tag) == {normal.interaction_id}
    assert await _inbox_ids(service, satish, "otp", search=tag) == {otp.interaction_id}


async def test_pagination_never_exposes_unauthorized_otps(db_session):
    satish = await _make_account_manager(db_session, "Satish")
    koushik = await _make_account_manager(db_session, "Koushik")
    client_a = await _make_client(db_session, account_manager_id=satish.user_id, label="A")
    client_b = await _make_client(db_session, account_manager_id=koushik.user_id, label="B")
    own = [await _make_email(db_session, is_otp=True, client_id=client_a.client_id) for _ in range(3)]
    others = [await _make_email(db_session, is_otp=True, client_id=client_b.client_id) for _ in range(3)]
    service = InboxService(InteractionRepository(db_session))

    seen = set()
    offset = 0
    while True:
        page = await service.get_inbox(satish, view="otp", limit=2, offset=offset)
        assert page.total == 3
        if not page.items:
            break
        seen |= {item.interaction_id for item in page.items}
        offset += len(page.items)

    assert seen == {otp.interaction_id for otp in own}
    assert not (seen & {otp.interaction_id for otp in others})


async def test_unauthorized_otp_cannot_be_opened_by_id(db_session):
    satish = await _make_account_manager(db_session, "Satish")
    koushik = await _make_account_manager(db_session, "Koushik")
    client_a = await _make_client(db_session, account_manager_id=satish.user_id, label="A")
    otp = await _make_email(db_session, is_otp=True, client_id=client_a.client_id)
    service = OpenEmailService(
        InteractionRepository(db_session),
        client_repository=ClientRepository(db_session),
        read_receipt_repository=MessageReadReceiptRepository(db_session),
        mail_folder_repository=MailFolderRepository(db_session),
        rule_repository=RuleRepository(db_session),
        distribution_list_repository=DistributionListRepository(db_session),
    )

    with pytest.raises(HTTPException) as exc_info:
        await service.get_email_details(otp.interaction_id, current_user=koushik)
    assert exc_info.value.status_code == 403

    opened = await service.get_email_details(otp.interaction_id, current_user=satish)
    assert opened.interaction_id == otp.interaction_id
    assert opened.is_read is True
