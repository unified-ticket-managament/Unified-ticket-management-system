# test_email_service_category_matching.py
#
# Focused coverage for the CATEGORY shared-mailbox feature added
# alongside the existing CLIENT shared-mailbox behavior covered by
# test_email_service_client_matching.py (kept unmodified as a
# regression guard — see that file's own tests). A CATEGORY mailbox
# (Category.inbox_email) is always a dedicated address, resolved the
# same way a client's own dedicated inbox_email already is, but routes
# to a Category + its Account Manager(s) (via ReportingManagerTeam)
# instead of a Client. No DB — every repository/service dependency
# below is a minimal fake exposing only what receive_email actually
# calls, mirroring test_email_service_client_matching.py's own
# convention exactly.

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


class _FakeCategory:
    def __init__(self, category_id, category_name, inbox_email):
        self.category_id = category_id
        self.category_name = category_name
        self.inbox_email = inbox_email


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
    def __init__(self, clients_by_email=None):
        self._clients_by_email = clients_by_email or {}

    async def get_active_by_inbox_email(self, email_address):
        return self._clients_by_email.get(email_address.strip().lower())

    async def get_active_by_any_email(self, email_address):
        return await self.get_active_by_inbox_email(email_address)


class _FakeCategoryRepository:
    def __init__(self, categories_by_email=None):
        self._categories_by_email = categories_by_email or {}

    async def get_active_by_inbox_email(self, email_address):
        return self._categories_by_email.get(email_address.strip().lower())


class _FakeReportingManagerRepository:
    def __init__(self, account_manager_ids_by_category=None):
        self._by_category = account_manager_ids_by_category or {}

    async def list_account_manager_ids_by_category(self, category_id):
        return list(self._by_category.get(category_id, []))


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
    def __init__(self, users_by_role=None):
        self._users_by_role = users_by_role or {}

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
        to_email="apm@probeps.com",
        from_email="patient@example.com",
        from_name="A Patient",
        subject="Question about my account",
        body="Hi, I have a question.",
        message_id=f"<{uuid4().hex}@example.com>",
    )
    base.update(overrides)
    return EmailRequest(**base)


async def test_receive_email_resolves_category_mailbox_not_client(monkeypatch):
    """
    The core new behavior: mail arriving at a CATEGORY mailbox
    (apm@probeps.com, mapped to the APM category) resolves a Category,
    never a Client — client_id/client_name stay None, category_id/
    category_name are set, and it is never rejected as "Unknown inbox
    address." even though no Client row matches the address at all.
    """

    category_id = uuid4()
    category = _FakeCategory(
        category_id=category_id, category_name="APM", inbox_email="apm@probeps.com"
    )

    monkeypatch.setattr(
        "app.ticketing.services.email_service.get_settings",
        lambda: _settings(),
    )

    interaction_repository = _FakeInteractionRepository()

    service = EmailService(
        interaction_repository=interaction_repository,
        client_repository=_FakeClientRepository(),
        attachment_service=None,
        category_repository=_FakeCategoryRepository({"apm@probeps.com": category}),
    )

    response = await service.receive_email(
        _email_request(to_email="apm@probeps.com", landed_mailbox="apm@probeps.com")
    )

    assert response.client_id is None
    assert response.client_name is None
    assert response.category_id == str(category_id)
    assert response.category_name == "APM"

    assert len(interaction_repository.created) == 1
    created_interaction = interaction_repository.created[0]
    assert created_interaction.client_id is None
    assert created_interaction.category_id == category_id


async def test_receive_email_category_mailbox_notifies_reporting_manager_and_global_inbox(
    monkeypatch,
):
    """
    Category -> Account Manager resolution reuses the existing
    ReportingManagerTeam mapping (ReportingManagerRepository) — the
    resolved category's Account Manager(s) are notified, exactly the
    same "AM + global inbox roles" shape the Client-mailbox path
    already uses, just sourced from the category mapping instead of
    Client.account_manager_id.
    """

    category_id = uuid4()
    account_manager_id = uuid4()
    site_lead_id = uuid4()
    category = _FakeCategory(
        category_id=category_id,
        category_name="PATIENTOUTREACH",
        inbox_email="patientoutreach@probeps.com",
    )

    monkeypatch.setattr(
        "app.ticketing.services.email_service.get_settings",
        lambda: _settings(),
    )

    notification_service = _FakeNotificationService()

    service = EmailService(
        interaction_repository=_FakeInteractionRepository(),
        client_repository=_FakeClientRepository(),
        attachment_service=None,
        user_repository=_FakeUserRepository({"Site Lead": [_FakeUser(site_lead_id)]}),
        notification_service=notification_service,
        category_repository=_FakeCategoryRepository(
            {"patientoutreach@probeps.com": category}
        ),
        reporting_manager_repository=_FakeReportingManagerRepository(
            {category_id: [account_manager_id]}
        ),
    )

    await service.receive_email(
        _email_request(
            to_email="patientoutreach@probeps.com",
            landed_mailbox="patientoutreach@probeps.com",
        )
    )

    assert len(notification_service.calls) == 1
    recipient_ids, notification_type, kwargs = notification_service.calls[0]
    assert notification_type == "MAIL_RECEIVED"
    assert account_manager_id in recipient_ids
    assert site_lead_id in recipient_ids
    assert kwargs["title"] == "New mail from PATIENTOUTREACH"


async def test_receive_email_client_mailbox_unaffected_by_category_feature(monkeypatch):
    """
    Regression guard: a normal client mailbox is never mistaken for a
    category mailbox just because a CategoryRepository is now wired
    in — client resolution takes priority whenever the address doesn't
    match any configured category mailbox, exactly as before this
    feature existed.
    """

    account_manager_id = uuid4()
    client = _FakeClient(
        client_id=uuid4(),
        name="Family First",
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
        # A configured category repository that simply has no entry for
        # this address — proves familyfirst@probeps.com doesn't
        # "suddenly become" a category mailbox now that category
        # lookups happen at all.
        category_repository=_FakeCategoryRepository({}),
    )

    response = await service.receive_email(
        _email_request(
            to_email="familyfirst@probeps.com",
            from_email="patient@example.com",
            landed_mailbox="familyfirst@probeps.com",
        )
    )

    assert response.client_id == str(client.client_id)
    assert response.client_name == "Family First"
    assert response.category_id is None
    assert response.category_name is None


async def test_receive_email_unmatched_dedicated_address_still_rejected(monkeypatch):
    """
    An address that matches neither a client nor a category mailbox is
    still rejected as "Unknown inbox address." — adding category
    resolution doesn't widen what counts as a known mailbox.
    """

    monkeypatch.setattr(
        "app.ticketing.services.email_service.get_settings",
        lambda: _settings(),
    )

    service = EmailService(
        interaction_repository=_FakeInteractionRepository(),
        client_repository=_FakeClientRepository({}),
        attachment_service=None,
        category_repository=_FakeCategoryRepository({}),
    )

    raised = None
    try:
        await service.receive_email(
            _email_request(
                to_email="nobody@example.com",
                landed_mailbox="nobody@example.com",
            )
        )
    except ValueError as exc:
        raised = exc

    assert raised is not None
    assert str(raised) == "Unknown inbox address."


async def test_receive_email_dynamic_new_category_needs_no_code_change(monkeypatch):
    """
    A brand-new category created purely through admin configuration
    (no hardcoded category name anywhere in email_service.py) routes
    correctly — proves category routing is fully data-driven.
    """

    category_id = uuid4()
    category = _FakeCategory(
        category_id=category_id,
        category_name="CARDIOLOGY",
        inbox_email="cardiology@probeps.com",
    )

    monkeypatch.setattr(
        "app.ticketing.services.email_service.get_settings",
        lambda: _settings(),
    )

    service = EmailService(
        interaction_repository=_FakeInteractionRepository(),
        client_repository=_FakeClientRepository(),
        attachment_service=None,
        category_repository=_FakeCategoryRepository(
            {"cardiology@probeps.com": category}
        ),
    )

    response = await service.receive_email(
        _email_request(
            to_email="cardiology@probeps.com",
            landed_mailbox="cardiology@probeps.com",
        )
    )

    assert response.category_id == str(category_id)
    assert response.category_name == "CARDIOLOGY"
