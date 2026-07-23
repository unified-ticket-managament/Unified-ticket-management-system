# test_graph_mail_integration.py
#
# Pure-logic coverage for the Microsoft Graph mail integration seam —
# no DB, no real network call to Graph or Azure AD. Mirrors
# test_sla_sweep_auth.py's shape: exercise the auth-adjacent logic
# directly rather than spinning up the full app.

from app.core.config import Settings
from app.ticketing.api.mail_integration import _client_state_matches
from app.ticketing.schemas.mail_integration import (
    GraphEmailAddress,
    GraphItemBody,
    GraphRecipient,
    GraphWebhookNotificationItem,
    GraphWebhookResourceData,
    IncomingMailPayload,
)
from app.ticketing.schemas.payloads import OutboundEnvelope
from app.ticketing.services.graph_auth import _cached_graph_auth_client, build_graph_auth_client
from app.ticketing.services.graph_client import (
    _build_recipients,
    _build_send_mail_message,
    build_graph_mail_provider_client,
)
from app.ticketing.services.mail_provider import MockMailProviderClient, get_mail_provider_client
from app.ticketing.services.graph_subscription_service import is_fully_configured
from app.ticketing.services.email_service import is_configured_graph_mailbox
from app.ticketing.services.graph_mail_poller import is_ready_to_poll
from app.ticketing.services.mail_mapping_service import (
    _html_to_plain_text,
    map_external_email_to_interaction,
)


def _base_settings(**overrides) -> Settings:
    """
    A minimally-valid Settings instance for unit testing —
    database_url/jwt_secret_key/sla_sweep_shared_secret have no
    defaults in the real Settings model (config.py), so a direct
    constructor call must supply placeholder values for them; none of
    the tests below touch a real database or issue a real token.

    _env_file=None is deliberate and load-bearing: Settings' own
    model_config points at unified-backend/.env, and pydantic-settings
    falls back to that file for any field not passed explicitly here.
    Once real Graph credentials exist in a developer's own .env (as
    they now do, post Graph-integration setup), tests that assert
    "unconfigured" behavior would otherwise silently read those real
    values instead of being isolated — exactly the failure mode this
    surfaced. Every test in this file must go through this helper
    rather than constructing Settings() directly, or it loses this
    isolation.
    """

    return Settings(
        _env_file=None,
        database_url="postgresql+asyncpg://user:pass@localhost/test",
        jwt_secret_key="test-secret",
        sla_sweep_shared_secret="test-sweep-secret",
        **overrides,
    )


def _notification_item(client_state: str | None) -> GraphWebhookNotificationItem:
    return GraphWebhookNotificationItem(
        subscriptionId="sub-123",
        clientState=client_state,
        changeType="created",
        resource="/users/mailbox@example.com/messages/abc",
        resourceData=GraphWebhookResourceData(id="abc"),
    )


# ---------------------------------------------------------
# clientState verification (api/mail_integration.py)
# ---------------------------------------------------------


def test_client_state_matches_accepts_correct_secret(monkeypatch):
    settings = _base_settings(graph_webhook_client_state="correct-secret")
    monkeypatch.setattr(
        "app.ticketing.api.mail_integration.get_settings", lambda: settings
    )

    assert _client_state_matches(_notification_item("correct-secret")) is True


def test_client_state_matches_rejects_wrong_secret(monkeypatch):
    settings = _base_settings(graph_webhook_client_state="correct-secret")
    monkeypatch.setattr(
        "app.ticketing.api.mail_integration.get_settings", lambda: settings
    )

    assert _client_state_matches(_notification_item("wrong-secret")) is False


def test_client_state_matches_fails_closed_when_unconfigured(monkeypatch):
    """
    An unset expected clientState must never be treated as "anything
    matches" — it should always reject, the same fail-closed default
    every other not-yet-configured secret in this codebase uses.
    """

    settings = _base_settings(graph_webhook_client_state=None)
    monkeypatch.setattr(
        "app.ticketing.api.mail_integration.get_settings", lambda: settings
    )

    assert _client_state_matches(_notification_item(None)) is False
    assert _client_state_matches(_notification_item("anything")) is False


# ---------------------------------------------------------
# Provider-client factory switching (mail_provider.py)
# ---------------------------------------------------------


def test_get_mail_provider_client_defaults_to_mock_when_unconfigured():
    settings = _base_settings()

    client = get_mail_provider_client(settings)

    assert isinstance(client, MockMailProviderClient)


def test_get_mail_provider_client_returns_graph_client_once_fully_configured(monkeypatch):
    # msal.ConfidentialClientApplication.__init__ always performs a real
    # tenant-discovery HTTP call (see graph_auth.py's own comment) —
    # stub it out so this test exercises the factory-switching logic
    # without needing network access or a real Azure tenant.
    monkeypatch.setattr(
        "app.ticketing.services.graph_auth.msal.ConfidentialClientApplication",
        lambda **kwargs: object(),
    )
    _cached_graph_auth_client.cache_clear()

    settings = _base_settings(
        graph_tenant_id="tenant-id-a",
        graph_client_id="client-id",
        graph_client_secret="client-secret",
        graph_mailbox_address="mailbox@example.com",
    )

    client = get_mail_provider_client(settings)

    assert client.__class__.__name__ == "GraphMailProviderClient"


def test_build_graph_auth_client_none_when_any_field_missing():
    settings = _base_settings(graph_tenant_id="tenant-id", graph_client_id="client-id")
    # graph_client_secret intentionally omitted

    assert build_graph_auth_client(settings) is None


def test_build_graph_mail_provider_client_none_without_mailbox(monkeypatch):
    monkeypatch.setattr(
        "app.ticketing.services.graph_auth.msal.ConfidentialClientApplication",
        lambda **kwargs: object(),
    )
    _cached_graph_auth_client.cache_clear()

    settings = _base_settings(
        graph_tenant_id="tenant-id-b",
        graph_client_id="client-id",
        graph_client_secret="client-secret",
        # graph_mailbox_address intentionally omitted
    )
    auth_client = build_graph_auth_client(settings)

    assert build_graph_mail_provider_client(settings, auth_client) is None


# ---------------------------------------------------------
# Subscription-configuration gate (graph_subscription_service.py)
# ---------------------------------------------------------


def test_subscription_not_fully_configured_by_default():
    assert is_fully_configured(_base_settings()) is False


def test_subscription_fully_configured_when_every_field_set():
    settings = _base_settings(
        graph_tenant_id="tenant-id",
        graph_client_id="client-id",
        graph_client_secret="client-secret",
        graph_mailbox_address="mailbox@example.com",
        graph_webhook_client_state="secret-state",
        graph_webhook_notification_url="https://example.onrender.com/api/mail/incoming",
    )

    assert is_fully_configured(settings) is True


# ---------------------------------------------------------
# Envelope -> Graph sendMail body mapping (graph_client.py)
# ---------------------------------------------------------


def _envelope(**overrides) -> OutboundEnvelope:
    base = dict(
        from_email="clientinbox@example.com",
        to_email="patient@example.com",
        subject="Re: Test",
        message_id="<new-id@example.com>",
        body="Hello there.",
    )
    base.update(overrides)
    return OutboundEnvelope(**base)


def test_build_recipients_maps_each_address():
    result = _build_recipients(["a@example.com", "b@example.com"])

    assert result == [
        {"emailAddress": {"address": "a@example.com"}},
        {"emailAddress": {"address": "b@example.com"}},
    ]


def test_build_send_mail_message_never_sets_internet_message_headers():
    """
    Regression test for a real, live-confirmed bug: Graph's sendMail
    hard-rejects an internetMessageHeaders entry named In-Reply-To/
    References with a 400 InvalidInternetMessageHeader error, failing
    the entire send — not a silent no-op. A reply envelope (which
    always has in_reply_to/references set) must never produce a
    message body containing that key at all.
    """

    envelope = _envelope(
        in_reply_to="<original@example.com>",
        references=["<a@example.com>", "<original@example.com>"],
    )

    message = _build_send_mail_message(envelope)

    assert "internetMessageHeaders" not in message


def test_build_send_mail_message_maps_recipients_and_body():
    envelope = _envelope(cc=["cc@example.com"], bcc=["bcc@example.com"])

    message = _build_send_mail_message(envelope)

    assert message["subject"] == envelope.subject
    assert message["body"] == {"contentType": "Text", "content": envelope.body}
    assert message["toRecipients"] == [{"emailAddress": {"address": envelope.to_email}}]
    assert message["ccRecipients"] == [{"emailAddress": {"address": "cc@example.com"}}]
    assert message["bccRecipients"] == [{"emailAddress": {"address": "bcc@example.com"}}]


def test_build_send_mail_message_omits_empty_cc_bcc():
    envelope = _envelope()

    message = _build_send_mail_message(envelope)

    assert "ccRecipients" not in message
    assert "bccRecipients" not in message


# ---------------------------------------------------------
# Mock fetch_message stays schema-valid (mail_provider.py)
# ---------------------------------------------------------


async def test_mock_fetch_message_returns_valid_payload():
    client = MockMailProviderClient()

    payload = await client.fetch_message("some-id")

    assert payload.internetMessageId
    assert payload.toRecipients
    assert payload.body.content


# ---------------------------------------------------------
# Graph-mailbox Site Lead fallback routing (email_service.py)
# ---------------------------------------------------------


def test_is_configured_graph_mailbox_matches_configured_address():
    settings = _base_settings(graph_mailbox_address="support@example.com")

    assert is_configured_graph_mailbox("support@example.com", settings) is True


def test_is_configured_graph_mailbox_is_case_insensitive():
    settings = _base_settings(graph_mailbox_address="Support@Example.com")

    assert is_configured_graph_mailbox("support@example.com", settings) is True


def test_is_configured_graph_mailbox_rejects_other_addresses():
    settings = _base_settings(graph_mailbox_address="support@example.com")

    assert is_configured_graph_mailbox("someone-else@example.com", settings) is False


def test_is_configured_graph_mailbox_false_when_unconfigured():
    settings = _base_settings(graph_mailbox_address=None)

    assert is_configured_graph_mailbox("anything@example.com", settings) is False


# ---------------------------------------------------------
# Polling-based inbound path (graph_mail_poller.py)
# ---------------------------------------------------------


def test_is_ready_to_poll_false_by_default():
    assert is_ready_to_poll(_base_settings()) is False


def test_is_ready_to_poll_true_once_identity_and_mailbox_set():
    """
    Deliberately does NOT require graph_webhook_client_state/
    graph_webhook_notification_url — polling needs neither, unlike
    graph_subscription_service.is_fully_configured.
    """

    settings = _base_settings(
        graph_tenant_id="tenant-id",
        graph_client_id="client-id",
        graph_client_secret="client-secret",
        graph_mailbox_address="mailbox@example.com",
    )

    assert is_ready_to_poll(settings) is True


async def test_mock_provider_list_new_messages_returns_empty():
    from datetime import datetime, timezone

    client = MockMailProviderClient()

    messages = await client.list_new_messages(since=datetime.now(timezone.utc))

    assert messages == []


async def test_poll_new_messages_noop_when_unconfigured():
    from app.ticketing.services.graph_mail_poller import poll_new_messages

    # No DB session is ever opened for this case — poll_new_messages
    # returns before touching AsyncSessionLocal, so this is safe to
    # run with no database configured/available.
    await poll_new_messages(_base_settings())


# ---------------------------------------------------------
# HTML-to-plain-text body extraction (mail_mapping_service.py)
# ---------------------------------------------------------


def test_html_to_plain_text_strips_tags_and_keeps_visible_text():
    html = (
        "<html><head><meta http-equiv=\"Content-Type\" "
        "content=\"text/html; charset=utf-8\"></head>"
        "<body><div dir=\"ltr\">i am testing this appicar</div>"
        "Disclaimer: confidential.</body></html>"
    )

    text = _html_to_plain_text(html)

    assert "<" not in text and ">" not in text
    assert "i am testing this appicar" in text
    assert "Disclaimer: confidential." in text


def test_html_to_plain_text_strips_script_and_style_content():
    html = "<html><body><style>.x{color:red}</style><script>alert(1)</script>Hello</body></html>"

    text = _html_to_plain_text(html)

    assert "alert" not in text
    assert "color:red" not in text
    assert text.strip() == "Hello"


def _graph_payload(content: str, content_type: str = "html") -> IncomingMailPayload:
    return IncomingMailPayload(
        internetMessageId="<test@example.com>",
        subject="Test",
        from_=GraphRecipient(
            emailAddress=GraphEmailAddress(name="Sender", address="sender@example.com")
        ),
        toRecipients=[
            GraphRecipient(
                emailAddress=GraphEmailAddress(address="ticketing@probeps.com")
            )
        ],
        body=GraphItemBody(contentType=content_type, content=content),
    )


def test_map_external_email_to_interaction_derives_plain_body_from_html():
    payload = _graph_payload(
        "<html><body><div dir=\"ltr\">hello there</div></body></html>", "html"
    )

    email = map_external_email_to_interaction(payload)

    assert email.body == "hello there"
    assert email.html_body == payload.body.content


def test_map_external_email_to_interaction_leaves_plain_text_untouched():
    payload = _graph_payload("just plain text, no markup", "text")

    email = map_external_email_to_interaction(payload)

    assert email.body == "just plain text, no markup"
    assert email.html_body is None


def test_map_external_email_to_interaction_falls_back_to_raw_html_when_no_visible_text():
    # An image-only body with no extractable text at all — must never
    # produce an empty `body` (EmailRequest.body requires min_length=1).
    payload = _graph_payload('<html><body><img src="cid:image1.png"></body></html>', "html")

    email = map_external_email_to_interaction(payload)

    assert email.body  # non-empty
    assert email.html_body == payload.body.content


def test_map_external_email_to_interaction_propagates_provider_message_id():
    payload = _graph_payload("hello", "text")
    payload.id = "AAMkAGI2-real-graph-native-id"

    email = map_external_email_to_interaction(payload)

    assert email.provider_message_id == "AAMkAGI2-real-graph-native-id"


def test_map_external_email_to_interaction_provider_message_id_none_when_absent():
    payload = _graph_payload("hello", "text")
    assert payload.id is None

    email = map_external_email_to_interaction(payload)

    assert email.provider_message_id is None
