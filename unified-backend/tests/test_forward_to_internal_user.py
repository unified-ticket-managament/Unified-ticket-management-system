# test_forward_to_internal_user.py
#
# Pure-logic coverage for InteractionService.forward_to_internal_user
# — no DB, no real network/Graph call, no real background dispatch.
# Every repository/service dependency below is a minimal fake exposing
# only what the method actually calls, same convention as
# test_email_service_client_matching.py / test_outbound_dispatcher.py.
#
# Focus: the two things that must never be trusted from the frontend
# alone — (1) is the caller actually authorized to send from the
# selected client's mailbox, (2) does the selected recipient resolve
# to a real, active internal agent — plus the happy path's mailbox
# resolution and notification delivery.

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.ticketing.schemas.forward import ForwardToInternalUserRequest
from app.ticketing.services.interaction_service import InteractionService


class _FakeRole:
    def __init__(self, name):
        self.name = name


class _FakeUser:
    def __init__(self, user_id, name, email, role_name, is_active=True, permissions=None):
        self.user_id = user_id
        self.name = name
        self.email = email
        self.role = _FakeRole(role_name)
        self.is_active = is_active
        # ensure_has_permission reads this off the JWT-derived
        # attribute real User instances carry — the "current_user"
        # (the manager sending the forward) needs it; a recipient
        # candidate never has ensure_has_permission called against it.
        self.permissions = permissions if permissions is not None else ["communication:reply_external"]
        # build_agent_signature reads these — all nullable on the
        # real model, default unset here.
        self.designation = None
        self.department = None
        self.phone_number = None


class _FakeClient:
    def __init__(self, client_id, name, inbox_email, account_manager_id, is_active=True):
        self.client_id = client_id
        self.name = name
        self.inbox_email = inbox_email
        self.account_manager_id = account_manager_id
        self.is_active = is_active


class _FakeInteraction:
    def __init__(self, interaction_id, ticket_id=None, client_id=None):
        self.interaction_id = interaction_id
        self.ticket_id = ticket_id
        self.client_id = client_id
        self.payload = {}


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


class _FakeInteractionRepository:
    def __init__(self, original):
        self.db = _FakeDB()
        self._original = original
        self.created = None
        self.updated_payloads = []

    async def get_by_id(self, interaction_id):
        if self._original is not None and interaction_id == self._original.interaction_id:
            return self._original
        return None

    async def create(self, data):
        self.created = _FakeCreatedInteraction(
            interaction_id=uuid4(),
            payload=data.payload,
            message_id=data.message_id,
            client_id=data.client_id,
            parent_interaction_id=data.parent_interaction_id,
            subject=data.subject,
        )
        return self.created

    async def update(self, interaction, data):
        self.updated_payloads.append(data.payload)
        if data.payload is not None:
            interaction.payload = data.payload
        return interaction


class _FakeClientRepository:
    def __init__(self, clients_by_id):
        self._clients_by_id = clients_by_id

    async def get_by_id(self, client_id):
        return self._clients_by_id.get(client_id)


class _FakeUserRepository:
    def __init__(self, users_by_id):
        self._users_by_id = users_by_id

    async def get_by_id(self, user_id):
        return self._users_by_id.get(user_id)


class _FakeNotificationService:
    def __init__(self):
        self.calls = []

    async def notify(self, user_ids, notification_type, **kwargs):
        self.calls.append((set(user_ids), notification_type, kwargs))


def _build_service(*, original, clients_by_id, users_by_id, notification_service=None):
    return InteractionService(
        interaction_repository=_FakeInteractionRepository(original),
        ticket_repository=None,
        user_repository=_FakeUserRepository(users_by_id),
        client_repository=_FakeClientRepository(clients_by_id),
        notification_service=notification_service or _FakeNotificationService(),
    )


@pytest.fixture(autouse=True)
def _no_real_background_dispatch(monkeypatch):
    # schedule_delayed_send fires a real asyncio background task that
    # opens its own DB session after a real sleep — never appropriate
    # to actually trigger from a pure-logic test.
    monkeypatch.setattr(
        "app.ticketing.services.interaction_service.schedule_delayed_send",
        lambda interaction_id, envelope: None,
    )


async def test_forward_rejects_client_the_manager_does_not_own():
    """
    The core security requirement: the backend must independently
    re-validate the selected client mailbox, regardless of what the
    frontend's dropdown showed — an Account Manager submitting a
    client_id they don't own must be rejected, not silently sent.
    """

    manager_id = uuid4()
    other_manager_id = uuid4()
    # The original message being forwarded belongs to a client the
    # manager DOES own (so viewing/forwarding it at all is legitimate)
    # — the thing under test is the SEPARATELY selected "From" client
    # in the request, which they do NOT own.
    owned_client = _FakeClient(
        client_id=uuid4(),
        name="Manager's Own Client",
        inbox_email="ownclient@probeps.com",
        account_manager_id=manager_id,
    )
    original = _FakeInteraction(interaction_id=uuid4(), client_id=owned_client.client_id)
    unauthorized_client = _FakeClient(
        client_id=uuid4(),
        name="Someone Else's Client",
        inbox_email="other@probeps.com",
        account_manager_id=other_manager_id,
    )
    recipient = _FakeUser(uuid4(), "Employee X", "employee.x@probeps.com", "Staff")
    current_user = _FakeUser(manager_id, "Some Manager", "manager@probeps.com", "Account Manager")

    service = _build_service(
        original=original,
        clients_by_id={
            owned_client.client_id: owned_client,
            unauthorized_client.client_id: unauthorized_client,
        },
        users_by_id={recipient.user_id: recipient},
    )

    with pytest.raises(HTTPException) as exc_info:
        await service.forward_to_internal_user(
            interaction_id=original.interaction_id,
            request=ForwardToInternalUserRequest(
                client_id=unauthorized_client.client_id,
                recipient_user_id=recipient.user_id,
                subject="Fwd: test",
                message="forwarded content",
            ),
            current_user=current_user,
        )

    assert exc_info.value.status_code == 403


async def test_forward_rejects_invalid_recipient():
    """An inactive/nonexistent/non-agent recipient must be rejected —
    never resolved to whatever string the frontend happened to submit."""

    manager_id = uuid4()
    client = _FakeClient(
        client_id=uuid4(),
        name="FamilyFirst",
        inbox_email="familyfirst@probeps.com",
        account_manager_id=manager_id,
    )
    original = _FakeInteraction(interaction_id=uuid4(), client_id=client.client_id)
    current_user = _FakeUser(manager_id, "Some Manager", "manager@probeps.com", "Account Manager")

    service = _build_service(
        original=original,
        clients_by_id={client.client_id: client},
        users_by_id={},  # recipient_user_id resolves to nothing
    )

    with pytest.raises(HTTPException) as exc_info:
        await service.forward_to_internal_user(
            interaction_id=original.interaction_id,
            request=ForwardToInternalUserRequest(
                client_id=client.client_id,
                recipient_user_id=uuid4(),
                subject="Fwd: test",
                message="forwarded content",
            ),
            current_user=current_user,
        )

    assert exc_info.value.status_code == 400


async def test_forward_rejects_non_agent_recipient():
    """A Client/Viewer-role account is not a valid internal recipient,
    even if it's a real, active user."""

    manager_id = uuid4()
    client = _FakeClient(
        client_id=uuid4(),
        name="FamilyFirst",
        inbox_email="familyfirst@probeps.com",
        account_manager_id=manager_id,
    )
    original = _FakeInteraction(interaction_id=uuid4(), client_id=client.client_id)
    client_role_user = _FakeUser(uuid4(), "A Client Contact", "contact@familyfirst.com", "Client")
    current_user = _FakeUser(manager_id, "Some Manager", "manager@probeps.com", "Account Manager")

    service = _build_service(
        original=original,
        clients_by_id={client.client_id: client},
        users_by_id={client_role_user.user_id: client_role_user},
    )

    with pytest.raises(HTTPException) as exc_info:
        await service.forward_to_internal_user(
            interaction_id=original.interaction_id,
            request=ForwardToInternalUserRequest(
                client_id=client.client_id,
                recipient_user_id=client_role_user.user_id,
                subject="Fwd: test",
                message="forwarded content",
            ),
            current_user=current_user,
        )

    assert exc_info.value.status_code == 400


async def test_forward_happy_path_uses_client_mailbox_and_notifies_recipient():
    """
    An authorized manager forwarding to a real internal recipient:
    the envelope's From is the selected client's own configured
    mailbox (never a generic/shared address), the created interaction
    preserves the original/ticket/client relationships, and exactly
    the chosen recipient is notified.
    """

    manager_id = uuid4()
    client = _FakeClient(
        client_id=uuid4(),
        name="FamilyFirst",
        inbox_email="familyfirst@probeps.com",
        account_manager_id=manager_id,
    )
    original = _FakeInteraction(interaction_id=uuid4(), ticket_id=None, client_id=client.client_id)
    recipient = _FakeUser(uuid4(), "Employee X", "employee.x@probeps.com", "Staff")
    current_user = _FakeUser(manager_id, "Some Manager", "manager@probeps.com", "Account Manager")
    notification_service = _FakeNotificationService()

    service = _build_service(
        original=original,
        clients_by_id={client.client_id: client},
        users_by_id={recipient.user_id: recipient},
        notification_service=notification_service,
    )

    response = await service.forward_to_internal_user(
        interaction_id=original.interaction_id,
        request=ForwardToInternalUserRequest(
            client_id=client.client_id,
            recipient_user_id=recipient.user_id,
            subject="Fwd: Billing question",
            message="Please handle this one.",
        ),
        current_user=current_user,
    )

    assert response.recipient_user_id == recipient.user_id
    assert response.recipient_email == recipient.email

    created = service.interaction_repository.created
    assert created.client_id == client.client_id
    assert created.parent_interaction_id == original.interaction_id
    assert created.payload["envelope"]["from_email"] == "familyfirst@probeps.com"
    assert created.payload["envelope"]["to_email"] == recipient.email
    assert "Please handle this one." in created.payload["message"]
    # Signature is present (build_agent_signature always includes the
    # sender's own name).
    assert current_user.name in created.payload["message"]

    assert len(notification_service.calls) == 1
    recipient_ids, notification_type, kwargs = notification_service.calls[0]
    assert recipient_ids == {recipient.user_id}
    assert notification_type == "MAIL_FORWARDED"
    assert kwargs["related_entity_id"] == created.interaction_id


async def test_forward_falls_back_to_shared_mailbox_when_client_has_none():
    manager_id = uuid4()
    client = _FakeClient(
        client_id=uuid4(),
        name="No Mailbox Client",
        inbox_email=None,
        account_manager_id=manager_id,
    )
    original = _FakeInteraction(interaction_id=uuid4(), client_id=client.client_id)
    recipient = _FakeUser(uuid4(), "Employee X", "employee.x@probeps.com", "Staff")
    current_user = _FakeUser(manager_id, "Some Manager", "manager@probeps.com", "Account Manager")

    service = _build_service(
        original=original,
        clients_by_id={client.client_id: client},
        users_by_id={recipient.user_id: recipient},
    )

    await service.forward_to_internal_user(
        interaction_id=original.interaction_id,
        request=ForwardToInternalUserRequest(
            client_id=client.client_id,
            recipient_user_id=recipient.user_id,
            subject="Fwd: test",
            message="content",
        ),
        current_user=current_user,
    )

    created = service.interaction_repository.created
    # Falls back to the shared mailbox — never a crash, never a blank
    # From address, when the selected client has no dedicated mailbox.
    assert created.payload["envelope"]["from_email"]
    assert created.payload["envelope"]["from_email"] != ""


def test_forward_request_rejects_both_recipient_fields():
    """Exactly one of recipient_user_id/recipient_email is allowed —
    supplying both must be rejected at the schema layer, before any
    service logic runs."""

    with pytest.raises(ValidationError):
        ForwardToInternalUserRequest(
            client_id=uuid4(),
            recipient_user_id=uuid4(),
            recipient_email="external@example.com",
            subject="Fwd: test",
            message="content",
        )


def test_forward_request_rejects_neither_recipient_field():
    """Supplying neither recipient field must also be rejected — the
    request must always pick exactly one recipient kind."""

    with pytest.raises(ValidationError):
        ForwardToInternalUserRequest(
            client_id=uuid4(),
            subject="Fwd: test",
            message="content",
        )


async def test_forward_to_external_email_sends_real_outbound_with_no_notification():
    """
    A recipient_email (e.g. another client's mailbox) must be accepted
    without any internal-identity lookup/check, must produce a real
    outbound envelope addressed to that literal address, must never
    call notification_service.notify (there's no platform user to
    notify), and the response must carry recipient_user_id=None
    alongside the literal recipient_email.
    """

    manager_id = uuid4()
    client = _FakeClient(
        client_id=uuid4(),
        name="FamilyFirst",
        inbox_email="familyfirst@probeps.com",
        account_manager_id=manager_id,
    )
    original = _FakeInteraction(interaction_id=uuid4(), client_id=client.client_id)
    current_user = _FakeUser(manager_id, "Some Manager", "manager@probeps.com", "Account Manager")
    notification_service = _FakeNotificationService()

    service = _build_service(
        original=original,
        clients_by_id={client.client_id: client},
        # No user rows at all — an external-email forward must never
        # touch the user repository's lookup path.
        users_by_id={},
        notification_service=notification_service,
    )

    response = await service.forward_to_internal_user(
        interaction_id=original.interaction_id,
        request=ForwardToInternalUserRequest(
            client_id=client.client_id,
            recipient_email="client2@example.com",
            subject="Fwd: Billing question",
            message="Please see the attached billing question.",
        ),
        current_user=current_user,
    )

    assert response.recipient_user_id is None
    assert response.recipient_email == "client2@example.com"

    created = service.interaction_repository.created
    assert created.payload["envelope"]["from_email"] == "familyfirst@probeps.com"
    assert created.payload["envelope"]["to_email"] == "client2@example.com"
    assert created.payload["recipient_kind"] == "external_email"
    assert created.payload["recipient_email"] == "client2@example.com"
    assert "recipient_user_id" not in created.payload

    # No platform user exists to notify for an external address.
    assert notification_service.calls == []


async def test_forward_to_external_email_still_enforces_client_authorization():
    """The external-email branch must still go through the exact same
    ensure_can_compose_for_client check as the internal branch — an
    Account Manager can't forward from a client's mailbox they don't
    own just because the recipient is now a free-text email."""

    manager_id = uuid4()
    other_manager_id = uuid4()
    owned_client = _FakeClient(
        client_id=uuid4(),
        name="Manager's Own Client",
        inbox_email="ownclient@probeps.com",
        account_manager_id=manager_id,
    )
    original = _FakeInteraction(interaction_id=uuid4(), client_id=owned_client.client_id)
    unauthorized_client = _FakeClient(
        client_id=uuid4(),
        name="Someone Else's Client",
        inbox_email="other@probeps.com",
        account_manager_id=other_manager_id,
    )
    current_user = _FakeUser(manager_id, "Some Manager", "manager@probeps.com", "Account Manager")

    service = _build_service(
        original=original,
        clients_by_id={
            owned_client.client_id: owned_client,
            unauthorized_client.client_id: unauthorized_client,
        },
        users_by_id={},
    )

    with pytest.raises(HTTPException) as exc_info:
        await service.forward_to_internal_user(
            interaction_id=original.interaction_id,
            request=ForwardToInternalUserRequest(
                client_id=unauthorized_client.client_id,
                recipient_email="client2@example.com",
                subject="Fwd: test",
                message="forwarded content",
            ),
            current_user=current_user,
        )

    assert exc_info.value.status_code == 403
