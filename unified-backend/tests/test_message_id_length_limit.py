# test_message_id_length_limit.py
#
# Option B for the Taral Sharma mail-ingestion incident: EmailRequest.
# message_id (and the related in_reply_to/conversation_id/
# provider_message_id fields, plus their DB-mapped Interaction/
# InboundMailFailure counterparts) was widened from 255 to 998
# characters — RFC 5322 section 2.1.1's own hard limit on an unfolded
# header line — so a legitimate long Message-ID (observed from
# Microsoft Graph/Teams notifications) is stored and processed exactly
# as received instead of being rejected. The existing skip-on-
# ValidationError safety net (graph_mail_poller.py / mail_integration.py)
# is untouched and still guards against anything still over 998, or any
# other schema violation — see test_graph_mail_poller_multi_mailbox.py's
# own coverage of that boundary. No DB here — every EmailService
# dependency is a minimal fake, same convention as
# test_email_service_client_matching.py.

from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.ticketing.schemas.email import EmailRequest
from app.ticketing.schemas.mail_integration import (
    GraphEmailAddress,
    GraphItemBody,
    GraphRecipient,
    IncomingMailPayload,
)
from app.ticketing.services.email_service import EmailService
from app.ticketing.services.mail_mapping_service import map_external_email_to_interaction


def _email_request(**overrides) -> EmailRequest:
    base = dict(
        to_email="ticketing@probeps.com",
        from_email="sender@example.com",
        subject="Test",
        body="Hello",
        message_id="<short-id@example.com>",
    )
    base.update(overrides)
    return EmailRequest(**base)


def _id_of_length(length: int) -> str:
    """A Message-ID-shaped string of exactly `length` characters —
    computed rather than hand-counted, so the boundary tests below are
    never off-by-one/two on padding arithmetic."""

    return "<" + ("a" * (length - 2)) + ">"


def test_message_id_of_exactly_255_chars_is_accepted():
    # The old boundary — must still work unchanged.
    message_id = _id_of_length(255)
    assert len(message_id) == 255
    assert _email_request(message_id=message_id).message_id == message_id


def test_message_id_of_500_chars_is_now_accepted():
    # Previously rejected outright (ValidationError) — the core fix.
    message_id = _id_of_length(500)
    request = _email_request(message_id=message_id)
    # Exact, byte-for-byte — never truncated, hashed, or altered.
    assert request.message_id == message_id


def test_message_id_of_exactly_998_chars_is_accepted():
    message_id = _id_of_length(998)
    assert _email_request(message_id=message_id).message_id == message_id


def test_message_id_over_998_chars_is_still_rejected():
    # Confirms the new limit is a deliberate finite ceiling, not
    # accidentally unlimited.
    message_id = _id_of_length(999)
    with pytest.raises(ValidationError):
        _email_request(message_id=message_id)


def _graph_payload(internet_message_id: str) -> IncomingMailPayload:
    return IncomingMailPayload(
        internetMessageId=internet_message_id,
        subject="Long ID test",
        from_=GraphRecipient(emailAddress=GraphEmailAddress(address="sender@example.com")),
        toRecipients=[
            GraphRecipient(emailAddress=GraphEmailAddress(address="ticketing@probeps.com"))
        ],
        body=GraphItemBody(contentType="text", content="hello"),
    )


def test_long_message_id_survives_mapping_without_truncation():
    long_id = _id_of_length(500)

    email_request = map_external_email_to_interaction(_graph_payload(long_id))

    assert email_request.message_id == long_id


# ---------------------------------------------------------
# Deduplication with a long message_id — same convention as
# test_email_service_client_matching.py's fakes.
# ---------------------------------------------------------


class _FakeDB:
    def add(self, obj):
        pass

    async def flush(self):
        pass

    async def refresh(self, obj):
        pass


class _FakeUser:
    def __init__(self, user_id):
        self.user_id = user_id


class _FakeClientRepository:
    async def get_active_by_inbox_email(self, email_address):
        return None

    async def get_active_by_any_email(self, email_address):
        return None


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


class _StatefulInteractionRepository:
    """Tracks stored message_ids in-memory so a second receive_email
    call with the same message_id sees it as already-processed —
    mirrors the real InteractionRepository.exists_by_message_id +
    interactions_message_id_key unique-constraint behavior without a
    real database."""

    def __init__(self):
        self.db = _FakeDB()
        self._stored_message_ids: set[str] = set()
        self.created = []

    async def exists_by_message_id(self, message_id):
        return message_id in self._stored_message_ids

    async def get_by_conversation_id(self, conversation_id):
        return []

    async def get_by_message_ids(self, message_ids):
        return []

    async def find_orphans_awaiting_parent(self, message_id):
        return []

    async def create(self, interaction_create):
        class _Created:
            pass

        created = _Created()
        created.interaction_id = uuid4()
        created.status = interaction_create.status
        self.created.append(interaction_create)
        self._stored_message_ids.add(interaction_create.message_id)
        return created


async def test_long_message_id_is_still_detected_as_duplicate_on_redelivery(monkeypatch):
    long_id = _id_of_length(500)

    site_lead_id = uuid4()
    settings = Settings(
        _env_file=None,
        database_url="postgresql+asyncpg://user:pass@localhost/test",
        jwt_secret_key="test-secret",
        sla_sweep_shared_secret="test-sweep-secret",
        graph_mailbox_address="ticketing@probeps.com",
    )
    monkeypatch.setattr(
        "app.ticketing.services.email_service.get_settings",
        lambda: settings,
    )

    interaction_repository = _StatefulInteractionRepository()
    service = EmailService(
        interaction_repository=interaction_repository,
        client_repository=_FakeClientRepository(),
        attachment_service=None,
        user_repository=_FakeUserRepository({"Site Lead": [_FakeUser(site_lead_id)]}),
        notification_service=_FakeNotificationService(),
    )

    request = _email_request(message_id=long_id, from_email="unknown-sender@example.com")

    first = await service.receive_email(request)
    assert first is not None

    with pytest.raises(ValueError, match="Email already processed."):
        await service.receive_email(request)

    # The exact 500-character string was what got compared, not a
    # truncated/hashed stand-in.
    assert interaction_repository.created[0].message_id == long_id
