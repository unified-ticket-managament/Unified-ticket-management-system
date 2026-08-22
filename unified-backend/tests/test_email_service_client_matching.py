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

    async def get_active_by_any_email(self, email_address):
        # The real repository tries inbox_email first, then falls back
        # to ClientContact — this fake has no separate contacts
        # concept, so it reuses the same lookup, which is sufficient
        # for every test in this file (none exercise the
        # contacts-fallback branch specifically).
        return await self.get_active_by_inbox_email(email_address)


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


async def test_receive_email_mail_received_notification_links_to_specific_message(monkeypatch):
    """
    Regression test for a real navigation bug: MAIL_RECEIVED notifications
    used to hardcode link="/inbox" even though the triggering interaction's
    id was already available, so clicking one always opened the generic
    inbox instead of the specific message — unlike every other mail-shaped
    notification (e.g. sla_breach_notifier's first-response threshold
    notifications), which already link f"/inbox?interaction_id={id}".
    MAIL_RECEIVED must match that same pattern.

    Uses the legacy (non-shared-mailbox) to_email match, same as
    test_receive_email_legacy_to_email_matching_still_works_off_shared_mailbox
    above, since that path only calls the fake client repository's
    already-implemented get_active_by_inbox_email — this test is about
    the notification link, not client-matching, so it deliberately
    avoids the shared-mailbox get_active_by_any_email path.
    """

    account_manager_id = uuid4()
    site_lead_id = uuid4()
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
    notification_service = _FakeNotificationService()

    service = EmailService(
        interaction_repository=interaction_repository,
        client_repository=_FakeClientRepository({"metro@probeps.com": client}),
        attachment_service=None,
        user_repository=_FakeUserRepository({"Site Lead": [_FakeUser(site_lead_id)]}),
        notification_service=notification_service,
    )

    await service.receive_email(
        _email_request(to_email="metro@probeps.com", from_email="someone@example.com")
    )

    assert len(interaction_repository.created) == 1
    assert len(notification_service.calls) == 1
    _, notification_type, kwargs = notification_service.calls[0]
    assert notification_type == "MAIL_RECEIVED"
    created_interaction_id = kwargs["related_entity_id"]
    assert kwargs["link"] == f"/inbox?interaction_id={created_interaction_id}"


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


async def test_receive_email_matches_client_by_dedicated_mailbox_arrival(monkeypatch):
    """
    The multi-mailbox Graph feature's actual client-identification
    contract: an email arriving at a client's own dedicated,
    Graph-pollable mailbox (e.g. familyfirst@probeps.com — a real
    onboarded client mailbox, not the legacy shared one) resolves that
    client by `to_email` regardless of who sent it, exactly like
    test_receive_email_legacy_to_email_matching_still_works_off_shared_mailbox
    above exercises for the pre-existing "legacy dedicated inbox"
    case — same code path, named explicitly for this feature so a
    regression here is easy to find.
    """

    account_manager_id = uuid4()
    client = _FakeClient(
        client_id=uuid4(),
        name="FamilyFirst",
        inbox_email="familyfirst@probeps.com",
        account_manager_id=account_manager_id,
    )

    monkeypatch.setattr(
        "app.ticketing.services.email_service.get_settings",
        lambda: _settings(),
    )

    interaction_repository = _FakeInteractionRepository()

    service = EmailService(
        interaction_repository=interaction_repository,
        client_repository=_FakeClientRepository({"familyfirst@probeps.com": client}),
        attachment_service=None,
    )

    response = await service.receive_email(
        _email_request(to_email="familyfirst@probeps.com", from_email="customer@example.com")
    )

    assert response.client_id == str(client.client_id)
    assert response.client_name == "FamilyFirst"


# ---------------------------------------------------------------------
# landed_mailbox: the Graph-poller-only signal for "which mailbox did
# this message actually land in" (see EmailRequest.landed_mailbox's
# own docstring) — fixes a real bug where a message Cc'd/Bcc'd to a
# configured mailbox, with some unrelated address in To:, was
# misidentified as arriving at that unrelated address and rejected as
# "Unknown inbox address." even though Graph genuinely delivered it
# into the configured mailbox's own Inbox.
# ---------------------------------------------------------------------


async def test_receive_email_landed_mailbox_direct_to_still_works(monkeypatch):
    """
    (a) No regression: the real poller always supplies landed_mailbox
    alongside a normal direct-To arrival — the two signals agree, and
    resolution is unchanged from the pre-existing to_email-only case.
    """

    account_manager_id = uuid4()
    client = _FakeClient(
        client_id=uuid4(),
        name="Credentialing",
        inbox_email="credentialing@probeps.com",
        account_manager_id=account_manager_id,
    )

    monkeypatch.setattr(
        "app.ticketing.services.email_service.get_settings",
        lambda: _settings(),
    )

    service = EmailService(
        interaction_repository=_FakeInteractionRepository(),
        client_repository=_FakeClientRepository({"credentialing@probeps.com": client}),
        attachment_service=None,
    )

    response = await service.receive_email(
        _email_request(
            to_email="credentialing@probeps.com",
            from_email="customer@example.com",
            landed_mailbox="credentialing@probeps.com",
        )
    )

    assert response.client_id == str(client.client_id)
    assert response.client_name == "Credentialing"


async def test_receive_email_landed_mailbox_matches_cc_recipient(monkeypatch):
    """
    (b) The bug this feature fixes: the configured mailbox appears only
    in Cc, with an unrelated address in To: — landed_mailbox (what the
    poller actually polled) must win over the irrelevant to_email
    header.
    """

    account_manager_id = uuid4()
    client = _FakeClient(
        client_id=uuid4(),
        name="Credentialing",
        inbox_email="credentialing@probeps.com",
        account_manager_id=account_manager_id,
    )

    monkeypatch.setattr(
        "app.ticketing.services.email_service.get_settings",
        lambda: _settings(),
    )

    service = EmailService(
        interaction_repository=_FakeInteractionRepository(),
        client_repository=_FakeClientRepository({"credentialing@probeps.com": client}),
        attachment_service=None,
    )

    response = await service.receive_email(
        _email_request(
            to_email="some-other-address@example.com",
            cc=["credentialing@probeps.com"],
            from_email="customer@example.com",
            landed_mailbox="credentialing@probeps.com",
        )
    )

    assert response.client_id == str(client.client_id)
    assert response.client_name == "Credentialing"


async def test_receive_email_landed_mailbox_matches_bcc_delivery(monkeypatch):
    """
    (c) Bcc delivery: Graph never surfaces Bcc in toRecipients/
    ccRecipients on the recipient's own copy at all, so neither
    to_email nor cc mentions the configured mailbox anywhere — only
    landed_mailbox (which mailbox's Inbox Graph actually returned this
    message from) carries the signal.
    """

    account_manager_id = uuid4()
    client = _FakeClient(
        client_id=uuid4(),
        name="Credentialing",
        inbox_email="credentialing@probeps.com",
        account_manager_id=account_manager_id,
    )

    monkeypatch.setattr(
        "app.ticketing.services.email_service.get_settings",
        lambda: _settings(),
    )

    service = EmailService(
        interaction_repository=_FakeInteractionRepository(),
        client_repository=_FakeClientRepository({"credentialing@probeps.com": client}),
        attachment_service=None,
    )

    response = await service.receive_email(
        _email_request(
            to_email="some-other-address@example.com",
            cc=[],
            from_email="customer@example.com",
            landed_mailbox="credentialing@probeps.com",
        )
    )

    assert response.client_id == str(client.client_id)
    assert response.client_name == "Credentialing"


async def test_receive_email_landed_mailbox_generic_for_another_client_mailbox(monkeypatch):
    """
    (d) The fix is generic, not Credentialing-specific: a different
    configured client mailbox (familyfirst@probeps.com) reached via Cc
    resolves the same way.
    """

    account_manager_id = uuid4()
    client = _FakeClient(
        client_id=uuid4(),
        name="FamilyFirst",
        inbox_email="familyfirst@probeps.com",
        account_manager_id=account_manager_id,
    )

    monkeypatch.setattr(
        "app.ticketing.services.email_service.get_settings",
        lambda: _settings(),
    )

    service = EmailService(
        interaction_repository=_FakeInteractionRepository(),
        client_repository=_FakeClientRepository({"familyfirst@probeps.com": client}),
        attachment_service=None,
    )

    response = await service.receive_email(
        _email_request(
            to_email="someone-else@example.com",
            cc=["familyfirst@probeps.com"],
            from_email="patient@example.com",
            landed_mailbox="familyfirst@probeps.com",
        )
    )

    assert response.client_id == str(client.client_id)
    assert response.client_name == "FamilyFirst"


async def test_receive_email_landed_mailbox_shared_mailbox_unchanged(monkeypatch):
    """
    (e) landed_mailbox equal to the configured shared mailbox still
    resolves by sender (get_active_by_any_email), exactly like today's
    to_email-based shared-mailbox detection — proves the shared-mailbox
    path (and its Site-Lead fallback) is unaffected by this fix, even
    when the shared mailbox itself was only Cc'd rather than being the
    literal To: address.
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

    notification_service = _FakeNotificationService()

    service = EmailService(
        interaction_repository=_FakeInteractionRepository(),
        client_repository=_FakeClientRepository({"gogineni@painmedpa.com": client}),
        attachment_service=None,
        user_repository=_FakeUserRepository({"Site Lead": [_FakeUser(site_lead_id)]}),
        notification_service=notification_service,
    )

    response = await service.receive_email(
        _email_request(
            to_email="someone-else@example.com",
            cc=["ticketing@probeps.com"],
            from_email="gogineni@painmedpa.com",
            landed_mailbox="ticketing@probeps.com",
        )
    )

    assert response.client_id == str(client.client_id)

    recipient_ids, _, _ = notification_service.calls[0]
    assert account_manager_id in recipient_ids
    assert site_lead_id in recipient_ids


async def test_receive_email_landed_mailbox_unconfigured_still_rejected(monkeypatch):
    """
    (f) Defensive case: a landed_mailbox that matches neither the
    shared mailbox nor any active client's inbox_email still raises
    "Unknown inbox address." — this shouldn't happen structurally
    (graph_mail_poller.py only ever passes an address it resolved from
    _resolve_mailboxes_to_poll), but the fix must never start trusting
    an arbitrary landed_mailbox value as if it were configured.
    """

    monkeypatch.setattr(
        "app.ticketing.services.email_service.get_settings",
        lambda: _settings(),
    )

    service = EmailService(
        interaction_repository=_FakeInteractionRepository(),
        client_repository=_FakeClientRepository({}),
        attachment_service=None,
    )

    raised = None
    try:
        await service.receive_email(
            _email_request(
                to_email="whatever@example.com",
                from_email="someone@example.com",
                landed_mailbox="not-a-configured-mailbox@example.com",
            )
        )
    except ValueError as exc:
        raised = exc

    assert raised is not None
    assert str(raised) == "Unknown inbox address."
