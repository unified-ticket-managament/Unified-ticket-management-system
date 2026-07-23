# test_email_service_client_matching.py
#
# Focused coverage for the client-lookup fix in
# EmailService.receive_email: once every real client sends into the
# single configured Microsoft Graph shared mailbox, `to_email` is
# identical for every client and can no longer resolve which one an
# inbound message belongs to — the sender's own address does instead
# (Client.inbox_email, despite the name, now stores that real address).
# No DB — every repository/service dependency below is a minimal fake
# exposing only what receive_email actually calls.

from uuid import uuid4

from app.core.config import Settings
from app.ticketing.schemas.email import EmailRequest
from app.ticketing.services.email_service import EmailService


def _settings(**overrides) -> Settings:
    base = dict(
        database_url="postgresql+asyncpg://user:pass@localhost/test",
        jwt_secret_key="test-secret",
        sla_sweep_shared_secret="test-sweep-secret",
        graph_mailbox_address="ticketing@probeps.com",
    )
    base.update(overrides)
    return Settings(_env_file=None, **base)


class _FakeClient:
    def __init__(self, client_id, name, inbox_email, account_manager_id):
        self.client_id = client_id
        self.name = name
        self.inbox_email = inbox_email
        self.account_manager_id = account_manager_id


class _FakeUser:
    def __init__(self, user_id):
        self.user_id = user_id


class _FakeDB:
    def add(self, obj):
        pass

    async def flush(self):
        pass

    async def refresh(self, obj):
        pass


class _FakeClientRepository:
    def __init__(self, clients_by_email):
        self._clients_by_email = clients_by_email

    async def get_active_by_inbox_email(self, email_address):
        return self._clients_by_email.get(email_address.strip().lower())


class _FakeInteractionRepository:
    def __init__(self):
        self.db = _FakeDB()
        self.created = []

    async def exists_by_message_id(self, message_id):
        return False

    async def get_by_conversation_id(self, conversation_id):
        return []

    async def get_by_message_ids(self, message_ids):
        return []

    async def create(self, interaction_create):
        class _Created:
            pass

        created = _Created()
        created.interaction_id = uuid4()
        created.status = interaction_create.status
        self.created.append(interaction_create)
        return created


class _FakeUserRepository:
    def __init__(self, users_by_role):
        self._users_by_role = users_by_role

    async def list_active_by_role_name(self, role_name):
        return self._users_by_role.get(role_name, [])

    async def get_by_id(self, user_id):
        return None


class _FakeNotificationService:
    def __init__(self):
        self.calls = []

    async def notify(self, recipient_ids, notification_type, **kwargs):
        self.calls.append((set(recipient_ids), notification_type, kwargs))


def _email_request(**overrides) -> EmailRequest:
    base = dict(
        to_email="ticketing@probeps.com",
        from_email="gogineni@painmedpa.com",
        from_name="Gogineni",
        subject="Question about billing",
        body="Hi, I have a question.",
        message_id=f"<{uuid4().hex}@painmedpa.com>",
    )
    base.update(overrides)
    return EmailRequest(**base)


async def test_receive_email_matches_client_by_sender_at_shared_mailbox(monkeypatch):
    """
    The core fix: mail arriving at the configured Graph shared mailbox
    is matched by `from_email` (the sender), not `to_email` (which is
    the same address for every client and can no longer distinguish
    them). A resolved client also routes to both its own Account
    Manager and the global Site Lead inbox in one notification call —
    pre-existing behavior, exercised here to confirm the fix doesn't
    accidentally fall back to the client-less/Site-Lead-only path.
    """

    account_manager_id = uuid4()
    site_lead_id = uuid4()
    client = _FakeClient(
        client_id=uuid4(),
        name="Gogineni Clinic",
        inbox_email="gogineni@painmedpa.com",
        account_manager_id=account_manager_id,
    )

    monkeypatch.setattr(
        "app.ticketing.services.email_service.get_settings",
        lambda: _settings(),
    )

    interaction_repository = _FakeInteractionRepository()
    notification_service = _FakeNotificationService()

    service = EmailService(
        interaction_repository=interaction_repository,
        client_repository=_FakeClientRepository({"gogineni@painmedpa.com": client}),
        attachment_service=None,
        user_repository=_FakeUserRepository({"Site Lead": [_FakeUser(site_lead_id)]}),
        notification_service=notification_service,
    )

    response = await service.receive_email(_email_request())

    assert response.client_id == str(client.client_id)
    assert response.client_name == "Gogineni Clinic"

    assert len(notification_service.calls) == 1
    recipient_ids, _, _ = notification_service.calls[0]
    assert account_manager_id in recipient_ids
    assert site_lead_id in recipient_ids


async def test_receive_email_falls_back_to_site_lead_for_unknown_sender(monkeypatch):
    """
    A sender that isn't any onboarded client's address still isn't
    rejected as "Unknown inbox address" at the shared mailbox — it
    routes to Site Lead only, same as before this fix (previously that
    was every message; now it's only ones from an unrecognized sender).
    """

    site_lead_id = uuid4()

    monkeypatch.setattr(
        "app.ticketing.services.email_service.get_settings",
        lambda: _settings(),
    )

    interaction_repository = _FakeInteractionRepository()
    notification_service = _FakeNotificationService()

    service = EmailService(
        interaction_repository=interaction_repository,
        client_repository=_FakeClientRepository({}),
        attachment_service=None,
        user_repository=_FakeUserRepository({"Site Lead": [_FakeUser(site_lead_id)]}),
        notification_service=notification_service,
    )

    response = await service.receive_email(
        _email_request(from_email="unknown-sender@example.com")
    )

    assert response.client_id is None
    assert response.client_name is None

    assert len(notification_service.calls) == 1
    recipient_ids, _, _ = notification_service.calls[0]
    assert recipient_ids == {site_lead_id}


async def test_receive_email_legacy_to_email_matching_still_works_off_shared_mailbox(monkeypatch):
    """
    An address other than the configured Graph shared mailbox (e.g. a
    still-dummy demo client's own dedicated inbox) keeps the original
    to_email-based match, regardless of who sent it — unaffected by
    this fix.
    """

    account_manager_id = uuid4()
    client = _FakeClient(
        client_id=uuid4(),
        name="Metro Family Care",
        inbox_email="metro@probeps.com",
        account_manager_id=account_manager_id,
    )

    monkeypatch.setattr(
        "app.ticketing.services.email_service.get_settings",
        lambda: _settings(),
    )

    interaction_repository = _FakeInteractionRepository()

    service = EmailService(
        interaction_repository=interaction_repository,
        client_repository=_FakeClientRepository({"metro@probeps.com": client}),
        attachment_service=None,
    )

    response = await service.receive_email(
        _email_request(to_email="metro@probeps.com", from_email="someone@example.com")
    )

    assert response.client_id == str(client.client_id)
    assert response.client_name == "Metro Family Care"
