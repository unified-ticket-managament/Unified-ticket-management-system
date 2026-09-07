# test_reply_external_forwarded_recipient_access.py
#
# Business requirement: a user holding communication:reply_external
# must be able to reply to a communication that was legitimately
# forwarded to them (or that they otherwise legitimately own/received)
# even when they are NOT the ticket owner/assigned agent — without
# turning communication:reply_external into a blanket "reply to any
# ticket" permission. Forwarded-to-a-*different*-user, and a totally
# unrelated ticket/item, must both still be denied.
#
# Covers both halves of the authorization stack:
# - Already-ticketed communications: InteractionService.add_reply +
#   access_control.ensure_agent_can_act_on_ticket/
#   ensure_agent_can_view_ticket/ensure_account_manager_owns_ticket_client.
# - Still-pending (pre-ticket) communications:
#   InteractionService.add_interaction_reply +
#   access_control.ensure_agent_can_view_pending_interaction (via
#   InteractionService._ensure_can_act_on_pending_interaction).
#
# Pure-logic, no DB — same fake-repository convention as
# test_forward_to_internal_user.py.

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.ticketing.enums import InteractionStatus, TicketStatus
from app.ticketing.schemas.ticket_action import InteractionReplyRequest, ReplyCreate
from app.ticketing.services import access_control
from app.ticketing.services.interaction_service import InteractionService


class _FakeRole:
    def __init__(self, name):
        self.name = name


class _FakeCategory:
    def __init__(self, category_name):
        self.category_name = category_name


class _FakeUser:
    def __init__(
        self,
        user_id,
        name,
        role_name,
        *,
        permissions=None,
        categories=None,
    ):
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
    def __init__(
        self,
        ticket_id,
        *,
        agent_id=None,
        ticket_type="Eligibility",
        client_company_id=None,
        current_status=TicketStatus.OPEN,
    ):
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
        category_id=None,
        parent_interaction_id=None,
        interaction_type="EMAIL",
        payload=None,
    ):
        self.interaction_id = interaction_id
        self.ticket_id = ticket_id
        self.client_id = client_id
        self.category_id = category_id
        self.parent_interaction_id = parent_interaction_id
        self.interaction_type = interaction_type
        self.payload = payload if payload is not None else {
            "subject": "Payment issue",
            "body": "original message body",
        }
        self.message_id = None
        self.subject = "Payment issue"
        # ASSIGNED (not PENDING/IGNORED) so add_interaction_reply's own
        # "leaves the pending triage queue" side effect is a no-op for
        # these tests — irrelevant to the authorization gate under test.
        self.status = InteractionStatus.ASSIGNED


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
    """
    In-memory thread store — every Interaction (root, replies, Forward
    rows) lives in `self.by_id`; find_thread_root/list_thread/
    list_by_ticket_id all derive from that one dict, mirroring the
    shape the real recursive-CTE repository methods expose.
    """

    def __init__(self, interactions=None):
        self.db = _FakeDB()
        self.by_id = {i.interaction_id: i for i in (interactions or [])}
        self.created = []

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

    async def list_thread(self, root_interaction_id):
        return [
            i for i in self.by_id.values()
            if i.parent_interaction_id == root_interaction_id
        ]

    async def list_by_ticket_id(self, ticket_id):
        return [i for i in self.by_id.values() if i.ticket_id == ticket_id]

    async def get_latest_inbound_email_for_ticket(self, ticket_id):
        # Skips real envelope-building entirely (see add_reply's own
        # `if latest_email is not None` branch) — irrelevant to the
        # authorization gate under test here.
        return None

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


class _FakeClient:
    def __init__(self, client_id, account_manager_id):
        self.client_id = client_id
        self.account_manager_id = account_manager_id


class _FakeClientRepository:
    def __init__(self, clients_by_id=None):
        self._by_id = clients_by_id or {}
        self.db = _FakeDB()

    async def get_by_id(self, client_id):
        return self._by_id.get(client_id)


class _FakeUserRepository:
    """Only backs _resolve_account_manager_email's best-effort Cc
    lookup here — a miss (None) is a normal, harmless outcome for that
    method, so an empty repository is a safe default."""

    def __init__(self, users_by_id=None):
        self._by_id = users_by_id or {}

    async def get_by_id(self, user_id):
        return self._by_id.get(user_id)


def _forward_row(*, parent_interaction_id, ticket_id, recipient_user_id):
    """A Forward row exactly as InteractionService.forward_to_internal_user
    creates it: parent_interaction_id points at the message forwarded,
    ticket_id carries over from the original (None pre-ticket, the real
    ticket_id once ticketed), payload["recipients"] names every internal
    recipient by user_id."""

    return _FakeInteraction(
        interaction_id=uuid4(),
        ticket_id=ticket_id,
        parent_interaction_id=parent_interaction_id,
        interaction_type="FORWARD",
        payload={
            "recipients": [
                {"user_id": str(recipient_user_id), "name": "Recipient", "email": "r@example.com"}
            ]
        },
    )


def _build_service(*, interactions, tickets=None, clients_by_id=None):
    return InteractionService(
        interaction_repository=_FakeInteractionRepository(interactions),
        ticket_repository=_FakeTicketRepository(tickets or []),
        user_repository=_FakeUserRepository(),
        client_repository=_FakeClientRepository(clients_by_id),
        distribution_list_repository=None,
    )


@pytest.fixture(autouse=True)
def _no_real_background_dispatch(monkeypatch):
    monkeypatch.setattr(
        "app.ticketing.services.interaction_service.schedule_delayed_send",
        lambda interaction_id, envelope: None,
    )


REPLY_EXTERNAL = "communication:reply_external"


# ---------------------------------------------------------
# Group A — access_control.ensure_agent_can_act_on_ticket
# (already-ticketed communications)
# ---------------------------------------------------------


async def test_act_on_ticket_denies_non_owner_with_no_relationship():
    """TEST 5-shaped (ticketed): a Staff member with reply_external but
    no ownership/forward relationship to the ticket must be denied."""

    ticket = _FakeTicket(uuid4(), agent_id=uuid4())
    stranger = _FakeUser(uuid4(), "Stranger", "Staff", permissions=[REPLY_EXTERNAL])

    with pytest.raises(HTTPException) as exc_info:
        await access_control.ensure_agent_can_act_on_ticket(
            ticket, stranger,
            permission_backed=REPLY_EXTERNAL,
            is_forward_recipient=False,
        )
    assert exc_info.value.status_code == 403


async def test_act_on_ticket_allows_confirmed_forward_recipient():
    """TEST 1: a non-owner, non-assignee holding reply_external who
    WAS confirmed as this ticket's forward recipient must be allowed."""

    ticket = _FakeTicket(uuid4(), agent_id=uuid4())
    user_b = _FakeUser(uuid4(), "User B", "Staff", permissions=[REPLY_EXTERNAL])

    # Must not raise.
    await access_control.ensure_agent_can_act_on_ticket(
        ticket, user_b,
        permission_backed=REPLY_EXTERNAL,
        is_forward_recipient=True,
    )


async def test_act_on_ticket_denies_forward_recipient_without_the_permission():
    """Holding forward-recipient status alone, without
    communication:reply_external itself, must still be denied — the
    permission is still a required half of the rule."""

    ticket = _FakeTicket(uuid4(), agent_id=uuid4())
    user_b = _FakeUser(uuid4(), "User B", "Staff", permissions=[])

    with pytest.raises(HTTPException) as exc_info:
        await access_control.ensure_agent_can_act_on_ticket(
            ticket, user_b,
            permission_backed=REPLY_EXTERNAL,
            is_forward_recipient=True,
        )
    assert exc_info.value.status_code == 403


async def test_act_on_ticket_bypasses_category_scope_for_forward_recipient():
    """A Staff member outside the ticket's own category would normally
    be blocked by ensure_agent_can_view_ticket's category gate before
    ever reaching the ownership check — a confirmed forward recipient
    must not be blocked there either."""

    ticket = _FakeTicket(uuid4(), agent_id=uuid4(), ticket_type="Claims")
    user_b = _FakeUser(
        uuid4(), "User B", "Staff",
        permissions=[REPLY_EXTERNAL],
        categories=[_FakeCategory("Eligibility")],  # different category
    )

    await access_control.ensure_agent_can_act_on_ticket(
        ticket, user_b,
        permission_backed=REPLY_EXTERNAL,
        is_forward_recipient=True,
    )


async def test_act_on_ticket_owner_path_unaffected():
    """Regression: the ticket's own assigned agent replying still
    works with no permission_backed/is_forward_recipient at all —
    existing behavior is untouched."""

    owner_id = uuid4()
    ticket = _FakeTicket(uuid4(), agent_id=owner_id)
    owner = _FakeUser(
        owner_id, "Owner", "Staff",
        permissions=["ticket:editown_ticket"],
        categories=[_FakeCategory("Eligibility")],
    )

    await access_control.ensure_agent_can_act_on_ticket(ticket, owner)


async def test_act_on_ticket_supervisor_bypass_unaffected():
    """Regression: a supervisor role (e.g. Team Lead) still bypasses
    ownership entirely, with no forward-recipient info needed."""

    ticket = _FakeTicket(uuid4(), agent_id=uuid4())
    team_lead = _FakeUser(
        uuid4(), "TL", "Team Lead", categories=[_FakeCategory("Eligibility")]
    )

    await access_control.ensure_agent_can_act_on_ticket(ticket, team_lead)


# ---------------------------------------------------------
# Group B — access_control.ensure_agent_can_view_pending_interaction
# (still-pending communications)
# ---------------------------------------------------------


async def test_pending_reply_denies_unrelated_holder_of_the_permission():
    """Tightened rule: communication:reply_external alone is no longer
    sufficient for a pending item with zero relationship to the user —
    this is the over-broad grant this fix closes."""

    item = _FakeInteraction(uuid4(), client_id=uuid4())
    stranger = _FakeUser(uuid4(), "Stranger", "Account Manager", permissions=[REPLY_EXTERNAL])

    with pytest.raises(HTTPException) as exc_info:
        await access_control.ensure_agent_can_view_pending_interaction(
            item, stranger, client_repository=None,
            permission_backed=REPLY_EXTERNAL,
            is_forward_recipient=False,
        )
    assert exc_info.value.status_code == 403


async def test_pending_reply_allows_confirmed_forward_recipient():
    item = _FakeInteraction(uuid4(), client_id=uuid4())
    user_b = _FakeUser(uuid4(), "User B", "Staff", permissions=[REPLY_EXTERNAL])

    await access_control.ensure_agent_can_view_pending_interaction(
        item, user_b, client_repository=None,
        permission_backed=REPLY_EXTERNAL,
        is_forward_recipient=True,
    )


async def test_pending_archive_permission_alone_still_sufficient():
    """Regression: communication:archive was never part of this
    narrowing — Archive keeps its pre-existing "permission alone,
    ownership aside" behavior."""

    item = _FakeInteraction(uuid4(), client_id=uuid4())
    stranger = _FakeUser(uuid4(), "Stranger", "Account Manager", permissions=["communication:archive"])

    await access_control.ensure_agent_can_view_pending_interaction(
        item, stranger, client_repository=None,
        permission_backed="communication:archive",
    )


# ---------------------------------------------------------
# Group C — InteractionService._is_ticket_forward_recipient /
# _is_forwarded_to_user (the recipient-matching logic itself)
# ---------------------------------------------------------


async def test_is_ticket_forward_recipient_matches_named_user():
    ticket_id = uuid4()
    root = _FakeInteraction(uuid4(), ticket_id=ticket_id)
    user_b = _FakeUser(uuid4(), "User B", "Staff")
    forward = _forward_row(
        parent_interaction_id=root.interaction_id, ticket_id=ticket_id,
        recipient_user_id=user_b.user_id,
    )

    service = _build_service(interactions=[root, forward])

    assert await service._is_ticket_forward_recipient(ticket_id, user_b) is True


async def test_is_ticket_forward_recipient_denies_different_user():
    """TEST 3/9: forwarded to User B must not also grant User C, even
    though the Forward row is on the same ticket thread."""

    ticket_id = uuid4()
    root = _FakeInteraction(uuid4(), ticket_id=ticket_id)
    user_b_id = uuid4()
    user_c = _FakeUser(uuid4(), "User C", "Staff")
    forward = _forward_row(
        parent_interaction_id=root.interaction_id, ticket_id=ticket_id,
        recipient_user_id=user_b_id,
    )

    service = _build_service(interactions=[root, forward])

    assert await service._is_ticket_forward_recipient(ticket_id, user_c) is False


# ---------------------------------------------------------
# Group D — InteractionService.add_reply end-to-end
# (already-ticketed communications)
# ---------------------------------------------------------


async def test_add_reply_allows_forwarded_non_owner_staff():
    """TEST 1 end-to-end: User A owns Ticket 123, forwards the email to
    User B. User B is not the owner/assignee, holds reply_external —
    the actual send must succeed."""

    owner_id = uuid4()
    ticket_id = uuid4()
    ticket = _FakeTicket(ticket_id, agent_id=owner_id, ticket_type="Eligibility")
    root = _FakeInteraction(uuid4(), ticket_id=ticket_id)
    user_b = _FakeUser(
        uuid4(), "User B", "Staff",
        permissions=[REPLY_EXTERNAL, "ticket:reply"],
        categories=[_FakeCategory("Claims")],  # deliberately a different category
    )
    forward = _forward_row(
        parent_interaction_id=root.interaction_id, ticket_id=ticket_id,
        recipient_user_id=user_b.user_id,
    )

    service = _build_service(interactions=[root, forward], tickets=[ticket])

    response = await service.add_reply(
        ticket_id=ticket_id,
        request=ReplyCreate(message="Thanks, I'll take it from here."),
        current_user=user_b,
    )

    assert response.ticket_id == ticket_id
    assert len(service.interaction_repository.created) == 1


async def test_add_reply_denies_forward_to_a_different_user():
    """TEST 3 end-to-end: the mail was forwarded to User B, not User C
    — User C must still be denied even though they hold reply_external
    and the ticket really was forwarded (just not to them)."""

    owner_id = uuid4()
    ticket_id = uuid4()
    ticket = _FakeTicket(ticket_id, agent_id=owner_id)
    root = _FakeInteraction(uuid4(), ticket_id=ticket_id)
    user_b_id = uuid4()
    user_c = _FakeUser(uuid4(), "User C", "Staff", permissions=[REPLY_EXTERNAL, "ticket:reply"])
    forward = _forward_row(
        parent_interaction_id=root.interaction_id, ticket_id=ticket_id,
        recipient_user_id=user_b_id,
    )

    service = _build_service(interactions=[root, forward], tickets=[ticket])

    with pytest.raises(HTTPException) as exc_info:
        await service.add_reply(
            ticket_id=ticket_id,
            request=ReplyCreate(message="I'll handle this."),
            current_user=user_c,
        )

    assert exc_info.value.status_code == 403
    assert service.interaction_repository.created == []


async def test_add_reply_denies_unrelated_ticket_despite_permission():
    """TEST 9/'unrelated ticket': reply_external must never become a
    blanket "reply to any ticket" grant — a ticket with no forward row
    at all must deny a non-owner holder of the permission."""

    ticket_id = uuid4()
    ticket = _FakeTicket(ticket_id, agent_id=uuid4())
    root = _FakeInteraction(uuid4(), ticket_id=ticket_id)
    stranger = _FakeUser(uuid4(), "Stranger", "Staff", permissions=[REPLY_EXTERNAL, "ticket:reply"])

    service = _build_service(interactions=[root], tickets=[ticket])

    with pytest.raises(HTTPException) as exc_info:
        await service.add_reply(
            ticket_id=ticket_id,
            request=ReplyCreate(message="I'll handle this."),
            current_user=stranger,
        )

    assert exc_info.value.status_code == 403
    assert service.interaction_repository.created == []


async def test_add_reply_owner_path_unaffected():
    """Regression: the ticket's own assigned agent (with no forwarding
    involved at all) can still reply normally."""

    owner_id = uuid4()
    ticket_id = uuid4()
    ticket = _FakeTicket(ticket_id, agent_id=owner_id)
    root = _FakeInteraction(uuid4(), ticket_id=ticket_id)
    owner = _FakeUser(
        owner_id, "Owner", "Staff",
        permissions=[REPLY_EXTERNAL, "ticket:reply", "ticket:editown_ticket"],
        categories=[_FakeCategory("Eligibility")],
    )

    service = _build_service(interactions=[root], tickets=[ticket])

    response = await service.add_reply(
        ticket_id=ticket_id,
        request=ReplyCreate(message="Following up as usual."),
        current_user=owner,
    )

    assert response.ticket_id == ticket_id


# ---------------------------------------------------------
# Group E — InteractionService.add_interaction_reply end-to-end
# (still-pending communications)
# ---------------------------------------------------------


async def test_add_interaction_reply_allows_forwarded_non_owner():
    """TEST 1, pre-ticket variant: a still-pending client mailbox item
    owned by a different Account Manager, forwarded to Staff User B —
    User B must be able to send the reply."""

    root_id = uuid4()
    client_id = uuid4()
    other_am_id = uuid4()
    root = _FakeInteraction(root_id, client_id=client_id)
    user_b = _FakeUser(uuid4(), "User B", "Staff", permissions=[REPLY_EXTERNAL])
    forward = _forward_row(
        parent_interaction_id=root_id, ticket_id=None, recipient_user_id=user_b.user_id
    )

    service = _build_service(
        interactions=[root, forward],
        clients_by_id={client_id: _FakeClient(client_id, other_am_id)},
    )

    response = await service.add_interaction_reply(
        interaction_id=root_id,
        request=InteractionReplyRequest(message="Sure, I can help with this."),
        current_user=user_b,
    )

    assert response.parent_interaction_id == root_id
    assert len(service.interaction_repository.created) == 1


async def test_add_interaction_reply_denies_forward_to_a_different_user():
    """TEST 3, pre-ticket variant."""

    root_id = uuid4()
    client_id = uuid4()
    other_am_id = uuid4()
    root = _FakeInteraction(root_id, client_id=client_id)
    user_b_id = uuid4()
    user_c = _FakeUser(uuid4(), "User C", "Staff", permissions=[REPLY_EXTERNAL])
    forward = _forward_row(
        parent_interaction_id=root_id, ticket_id=None, recipient_user_id=user_b_id
    )

    service = _build_service(
        interactions=[root, forward],
        clients_by_id={client_id: _FakeClient(client_id, other_am_id)},
    )

    with pytest.raises(HTTPException) as exc_info:
        await service.add_interaction_reply(
            interaction_id=root_id,
            request=InteractionReplyRequest(message="I'll take this."),
            current_user=user_c,
        )

    assert exc_info.value.status_code == 403
    assert service.interaction_repository.created == []


async def test_add_interaction_reply_allows_owning_account_manager():
    """TEST 2-shaped ('directly received'): the Account Manager who
    owns this client's mailbox can reply with no forwarding involved at
    all — the pre-existing ownership path is unaffected."""

    root_id = uuid4()
    client_id = uuid4()
    am = _FakeUser(uuid4(), "Owning AM", "Account Manager", permissions=[REPLY_EXTERNAL])
    root = _FakeInteraction(root_id, client_id=client_id)

    service = _build_service(
        interactions=[root],
        clients_by_id={client_id: _FakeClient(client_id, am.user_id)},
    )

    response = await service.add_interaction_reply(
        interaction_id=root_id,
        request=InteractionReplyRequest(message="Thanks for reaching out."),
        current_user=am,
    )

    assert response.parent_interaction_id == root_id


async def test_add_interaction_reply_denies_unrelated_user_despite_permission():
    """TEST 5/9: a user with reply_external but no ownership and no
    forward relationship to this pending item must be denied."""

    root_id = uuid4()
    client_id = uuid4()
    other_am_id = uuid4()
    root = _FakeInteraction(root_id, client_id=client_id)
    stranger = _FakeUser(uuid4(), "Stranger", "Account Manager", permissions=[REPLY_EXTERNAL])

    service = _build_service(
        interactions=[root],
        clients_by_id={client_id: _FakeClient(client_id, other_am_id)},
    )

    with pytest.raises(HTTPException) as exc_info:
        await service.add_interaction_reply(
            interaction_id=root_id,
            request=InteractionReplyRequest(message="I'll take this."),
            current_user=stranger,
        )

    assert exc_info.value.status_code == 403
    assert service.interaction_repository.created == []
