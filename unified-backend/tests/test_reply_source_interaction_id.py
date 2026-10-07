# test_reply_source_interaction_id.py
#
# Coverage for ReplyCreate.source_interaction_id /
# InteractionReplyRequest.source_interaction_id — the Mail module's
# per-message Reply/Reply All now lets the caller name exactly which
# message in a thread it's replying to, instead of
# InteractionService.add_reply/add_interaction_reply always silently
# resolving "the ticket's latest inbound email" / "the thread root".
#
# Pure-logic, no DB — same fake-repository convention as
# test_reply_external_forwarded_recipient_access.py /
# test_forward_to_internal_user.py.

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.ticketing.enums import InteractionDirection, InteractionStatus, TicketStatus
from app.ticketing.schemas.ticket_action import InteractionReplyRequest, ReplyCreate
from app.ticketing.services.interaction_service import InteractionService


class _FakeRole:
    def __init__(self, name):
        self.name = name


class _FakeCategory:
    def __init__(self, category_name):
        self.category_name = category_name


class _FakeUser:
    def __init__(self, user_id, name, role_name, *, permissions=None, categories=None):
        self.user_id = user_id
        self.name = name
        self.email = f"{name.lower().replace(' ', '.')}@probeps.com"
        self.role = _FakeRole(role_name)
        self.is_active = True
        self.permissions = permissions if permissions is not None else []
        self.categories = categories or []
        self.designation = None
        self.department = None
        self.phone_number = None


class _FakeTicket:
    def __init__(self, ticket_id, *, agent_id=None, ticket_type="Eligibility", client_company_id=None, current_status=TicketStatus.OPEN):
        self.ticket_id = ticket_id
        self.agent_id = agent_id
        self.ticket_type = ticket_type
        self.client_company_id = client_company_id
        self.current_status = current_status


class _FakeInteraction:
    def __init__(
        self,
        interaction_id,
        *,
        ticket_id=None,
        client_id=None,
        parent_interaction_id=None,
        interaction_type="EMAIL",
        payload=None,
        direction=InteractionDirection.INBOUND,
        provider_message_id=None,
        subject="Payment issue",
    ):
        self.interaction_id = interaction_id
        self.ticket_id = ticket_id
        self.client_id = client_id
        self.parent_interaction_id = parent_interaction_id
        self.interaction_type = interaction_type
        self.payload = payload if payload is not None else {"subject": subject, "body": "original message body"}
        self.message_id = None
        self.subject = subject
        self.status = InteractionStatus.ASSIGNED
        self.direction = direction
        self.provider_message_id = provider_message_id


class _FakeCreatedInteraction:
    def __init__(self, interaction_id, payload, message_id, client_id, parent_interaction_id, subject):
        self.interaction_id = interaction_id
        self.payload = payload
        self.message_id = message_id
        self.client_id = client_id
        self.parent_interaction_id = parent_interaction_id
        self.subject = subject
        self.created_at = datetime.now(timezone.utc)


class _FakeDB:
    def add(self, obj):
        pass

    async def flush(self):
        pass

    async def refresh(self, obj):
        pass

    async def commit(self):
        pass

    async def rollback(self):
        pass


class _FakeInteractionRepository:
    def __init__(self, interactions=None, *, latest_inbound_for_ticket=None):
        self.db = _FakeDB()
        self.by_id = {i.interaction_id: i for i in (interactions or [])}
        self.created = []
        self._latest_inbound_for_ticket = latest_inbound_for_ticket

    async def get_by_id(self, interaction_id):
        return self.by_id.get(interaction_id)

    async def find_thread_root(self, interaction_id):
        current = self.by_id.get(interaction_id)
        if current is None:
            return None
        while current.parent_interaction_id is not None:
            parent = self.by_id.get(current.parent_interaction_id)
            if parent is None:
                break
            current = parent
        return current

    async def get_latest_inbound_email_for_ticket(self, ticket_id):
        return self._latest_inbound_for_ticket

    async def get_by_idempotency_key(self, key, user_id):
        return None

    async def update(self, interaction, data):
        if data.status is not None:
            interaction.status = data.status
        return interaction

    async def create(self, data):
        created = _FakeCreatedInteraction(
            interaction_id=uuid4(),
            payload=data.payload,
            message_id=data.message_id,
            client_id=data.client_id,
            parent_interaction_id=data.parent_interaction_id,
            subject=data.subject,
        )
        self.created.append(created)
        self.by_id[created.interaction_id] = created
        return created


class _FakeTicketRepository:
    def __init__(self, tickets):
        self._by_id = {t.ticket_id: t for t in tickets}

    async def get_by_id(self, ticket_id):
        return self._by_id.get(ticket_id)


class _FakeClientRepository:
    async def get_by_id(self, client_id):
        return None


class _FakeUserRepository:
    async def get_by_id(self, user_id):
        return None


def _build_service(*, interactions, tickets=None, latest_inbound_for_ticket=None):
    return InteractionService(
        interaction_repository=_FakeInteractionRepository(
            interactions, latest_inbound_for_ticket=latest_inbound_for_ticket
        ),
        ticket_repository=_FakeTicketRepository(tickets or []),
        user_repository=_FakeUserRepository(),
        client_repository=_FakeClientRepository(),
        distribution_list_repository=None,
    )


@pytest.fixture(autouse=True)
def _no_real_background_dispatch(monkeypatch):
    monkeypatch.setattr(
        "app.ticketing.services.interaction_service.schedule_delayed_send",
        lambda interaction_id, envelope: None,
    )


def _owner_user(owner_id, ticket_type="Eligibility"):
    return _FakeUser(
        owner_id,
        "Owner",
        "Staff",
        permissions=["communication:reply_external", "ticket:reply", "ticket:editown_ticket"],
        categories=[_FakeCategory(ticket_type)],
    )


EMAIL_PAYLOAD = lambda from_email, to_email, subject: {
    "from_email": from_email,
    "to_email": to_email,
    "subject": subject,
    "body": "body text",
}

REPLY_PAYLOAD = lambda from_email, to_email, subject, provider_message_id=None: {
    "message": "a prior agent reply",
    "envelope": {
        "from_email": from_email,
        "from_name": "Support",
        "to_email": to_email,
        "subject": subject,
        "cc": [],
        "bcc": [],
        "references": [],
    },
}


# ---------------------------------------------------------
# add_reply (ticketed) — source_interaction_id
# ---------------------------------------------------------


async def test_add_reply_without_source_interaction_id_uses_latest_inbound():
    """Regression guard: omitting source_interaction_id (every existing
    caller, including Ticket Workspace's TicketComposer.tsx) must keep
    resolving exactly as before — envelope built from the ticket's
    latest inbound email, parent flattened to the true thread root
    (find_thread_root), never source_interaction_id-based chaining."""

    owner_id = uuid4()
    ticket_id = uuid4()
    ticket = _FakeTicket(ticket_id, agent_id=owner_id)
    older_message = _FakeInteraction(
        uuid4(), ticket_id=ticket_id,
        payload=EMAIL_PAYLOAD("client@example.com", "support@shared.com", "Eligibility Check"),
    )
    latest_message = _FakeInteraction(
        uuid4(), ticket_id=ticket_id, parent_interaction_id=older_message.interaction_id,
        payload=EMAIL_PAYLOAD("client@example.com", "support@shared.com", "Re: Eligibility Check"),
    )

    service = _build_service(
        interactions=[older_message, latest_message],
        tickets=[ticket],
        latest_inbound_for_ticket=latest_message,
    )

    await service.add_reply(
        ticket_id=ticket_id,
        request=ReplyCreate(message="Thanks for the update."),
        current_user=_owner_user(owner_id),
    )

    assert len(service.interaction_repository.created) == 1
    created = service.interaction_repository.created[0]
    # Flattened to the true root (find_thread_root), exactly as before
    # source_interaction_id existed — not latest_message's own id, and
    # emphatically not the one explicit per-message chaining uses.
    assert created.parent_interaction_id == older_message.interaction_id


async def test_add_reply_with_source_interaction_id_targets_that_message_not_latest():
    """The core new behavior: explicitly naming an OLDER message as
    source_interaction_id must build the reply from THAT message — its
    own sender becomes the envelope's To, and the new reply's parent
    chains directly off it — never the ticket's latest inbound email,
    even though one exists and would normally win."""

    owner_id = uuid4()
    ticket_id = uuid4()
    ticket = _FakeTicket(ticket_id, agent_id=owner_id)
    older_message = _FakeInteraction(
        uuid4(), ticket_id=ticket_id,
        payload=EMAIL_PAYLOAD("kimberly@example.com", "support@shared.com", "Eligibility Check"),
    )
    latest_message = _FakeInteraction(
        uuid4(), ticket_id=ticket_id, parent_interaction_id=older_message.interaction_id,
        payload=EMAIL_PAYLOAD("someone-else@example.com", "support@shared.com", "Re: Eligibility Check"),
    )

    service = _build_service(
        interactions=[older_message, latest_message],
        tickets=[ticket],
        latest_inbound_for_ticket=latest_message,
    )

    await service.add_reply(
        ticket_id=ticket_id,
        request=ReplyCreate(
            message="Replying to your original message.",
            source_interaction_id=older_message.interaction_id,
        ),
        current_user=_owner_user(owner_id),
    )

    created = service.interaction_repository.created[0]
    assert created.parent_interaction_id == older_message.interaction_id
    envelope = created.payload["envelope"]
    assert envelope["to_email"] == "kimberly@example.com"


async def test_add_reply_source_interaction_id_from_prior_reply_carries_provider_message_id():
    """Replying to a prior AGENT reply (not the original client email)
    must build the envelope from that reply's own stored
    OutboundEnvelope (payload['envelope']), targeting whoever that
    specific reply was sent to, and carrying over its own Graph
    provider_message_id so the new send is genuinely threaded against
    THAT message, not the thread root."""

    owner_id = uuid4()
    ticket_id = uuid4()
    ticket = _FakeTicket(ticket_id, agent_id=owner_id)
    root = _FakeInteraction(
        uuid4(), ticket_id=ticket_id,
        payload=EMAIL_PAYLOAD("kimberly@example.com", "support@shared.com", "Eligibility Check"),
    )
    prior_reply = _FakeInteraction(
        uuid4(),
        ticket_id=ticket_id,
        parent_interaction_id=root.interaction_id,
        interaction_type="REPLY",
        direction=InteractionDirection.OUTBOUND,
        provider_message_id="graph-msg-123",
        payload=REPLY_PAYLOAD("support@shared.com", "kimberly@example.com", "Re: Eligibility Check"),
    )

    service = _build_service(
        interactions=[root, prior_reply],
        tickets=[ticket],
        latest_inbound_for_ticket=root,
    )

    await service.add_reply(
        ticket_id=ticket_id,
        request=ReplyCreate(
            message="Following up on my own earlier reply.",
            source_interaction_id=prior_reply.interaction_id,
        ),
        current_user=_owner_user(owner_id),
    )

    created = service.interaction_repository.created[0]
    assert created.parent_interaction_id == prior_reply.interaction_id
    envelope = created.payload["envelope"]
    # The shared mailbox stays the From; the reply's own recipient
    # (not the root client email's sender) becomes the default To.
    assert envelope["from_email"] == "support@shared.com"
    assert envelope["to_email"] == "kimberly@example.com"
    assert envelope["reply_to_provider_message_id"] == "graph-msg-123"


async def test_add_reply_source_interaction_id_from_different_ticket_is_rejected():
    """A client-supplied source_interaction_id must be validated as
    belonging to THIS ticket — never trusted blindly, the same way
    attachment_source_interaction_id already is."""

    owner_id = uuid4()
    ticket_id = uuid4()
    other_ticket_id = uuid4()
    ticket = _FakeTicket(ticket_id, agent_id=owner_id)
    foreign_message = _FakeInteraction(
        uuid4(), ticket_id=other_ticket_id,
        payload=EMAIL_PAYLOAD("someone@example.com", "support@shared.com", "Unrelated ticket"),
    )

    service = _build_service(interactions=[foreign_message], tickets=[ticket])

    with pytest.raises(HTTPException) as exc_info:
        await service.add_reply(
            ticket_id=ticket_id,
            request=ReplyCreate(
                message="Trying to reply across tickets.",
                source_interaction_id=foreign_message.interaction_id,
            ),
            current_user=_owner_user(owner_id),
        )

    assert exc_info.value.status_code == 400
    assert service.interaction_repository.created == []


# ---------------------------------------------------------
# add_interaction_reply (pre-ticket) — source_interaction_id
# ---------------------------------------------------------


async def test_add_interaction_reply_with_source_interaction_id_targets_non_root_message():
    """Pre-ticket counterpart: naming a non-root message within the
    SAME thread as source_interaction_id must chain the new reply off
    it directly, not the thread root."""

    root_id = uuid4()
    client_id = uuid4()
    am = _FakeUser(uuid4(), "Owning AM", "Account Manager", permissions=["communication:reply_external"])
    root = _FakeInteraction(
        root_id, client_id=client_id,
        payload=EMAIL_PAYLOAD("kimberly@example.com", "support@shared.com", "Eligibility Check"),
    )
    middle_reply = _FakeInteraction(
        uuid4(),
        client_id=client_id,
        parent_interaction_id=root_id,
        interaction_type="REPLY",
        direction=InteractionDirection.OUTBOUND,
        payload=REPLY_PAYLOAD("support@shared.com", "kimberly@example.com", "Re: Eligibility Check"),
    )

    class _ClientRepo:
        async def get_by_id(self, _client_id):
            class _C:
                account_manager_id = am.user_id

            return _C()

    service = InteractionService(
        interaction_repository=_FakeInteractionRepository([root, middle_reply]),
        ticket_repository=_FakeTicketRepository([]),
        user_repository=_FakeUserRepository(),
        client_repository=_ClientRepo(),
        distribution_list_repository=None,
    )

    response = await service.add_interaction_reply(
        interaction_id=root_id,
        request=InteractionReplyRequest(
            message="Replying to my own earlier reply.",
            source_interaction_id=middle_reply.interaction_id,
        ),
        current_user=am,
    )

    assert response.parent_interaction_id == middle_reply.interaction_id
    created = service.interaction_repository.created[0]
    assert created.payload["envelope"]["to_email"] == "kimberly@example.com"


async def test_add_interaction_reply_source_interaction_id_from_different_thread_is_rejected():
    """A source_interaction_id that resolves to a DIFFERENT thread root
    must be rejected — this thread's reply can't be parented off some
    other, unrelated conversation."""

    root_id = uuid4()
    other_root_id = uuid4()
    client_id = uuid4()
    am = _FakeUser(uuid4(), "Owning AM", "Account Manager", permissions=["communication:reply_external"])
    root = _FakeInteraction(
        root_id, client_id=client_id,
        payload=EMAIL_PAYLOAD("kimberly@example.com", "support@shared.com", "Eligibility Check"),
    )
    other_root = _FakeInteraction(
        other_root_id, client_id=client_id,
        payload=EMAIL_PAYLOAD("someone-else@example.com", "support@shared.com", "A different conversation"),
    )

    class _ClientRepo:
        async def get_by_id(self, _client_id):
            class _C:
                account_manager_id = am.user_id

            return _C()

    service = InteractionService(
        interaction_repository=_FakeInteractionRepository([root, other_root]),
        ticket_repository=_FakeTicketRepository([]),
        user_repository=_FakeUserRepository(),
        client_repository=_ClientRepo(),
        distribution_list_repository=None,
    )

    with pytest.raises(HTTPException) as exc_info:
        await service.add_interaction_reply(
            interaction_id=root_id,
            request=InteractionReplyRequest(
                message="Trying to reply across threads.",
                source_interaction_id=other_root_id,
            ),
            current_user=am,
        )

    assert exc_info.value.status_code == 400
    assert service.interaction_repository.created == []
