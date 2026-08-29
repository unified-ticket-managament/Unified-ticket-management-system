# test_graph_mail_integration.py
#
# Pure-logic coverage for the Microsoft Graph mail integration seam —
# no DB, no real network call to Graph or Azure AD. Mirrors
# test_sla_sweep_auth.py's shape: exercise the auth-adjacent logic
# directly rather than spinning up the full app.

import logging

import pytest

from app.core.config import Settings
from app.ticketing.api.mail_integration import _client_state_matches
from app.ticketing.schemas.mail_integration import (
    GraphAttachmentPayload,
    GraphEmailAddress,
    GraphItemBody,
    GraphRecipient,
    GraphWebhookNotificationItem,
    GraphWebhookResourceData,
    IncomingMailPayload,
)
from app.ticketing.schemas.payloads import EnvelopeAttachment, OutboundEnvelope
from app.ticketing.services.graph_auth import _cached_graph_auth_client, build_graph_auth_client
from app.ticketing.services.graph_client import (
    _build_recipients,
    _build_reply_action_body,
    _build_send_mail_message,
    build_graph_mail_provider_client,
)
from app.ticketing.services.mail_provider import MockMailProviderClient, get_mail_provider_client
from app.ticketing.services.graph_subscription_service import is_fully_configured
from app.ticketing.services.email_service import is_configured_graph_mailbox
from app.ticketing.services.graph_mail_poller import is_ready_to_poll
from app.ticketing.services.mail_mapping_service import (
    _html_to_plain_text,
    build_upload_files_from_graph_attachments,
    map_external_email_to_interaction,
)
from app.ticketing.utils.validators import validate_attachment_type


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


async def test_process_graph_notification_passes_landed_mailbox_for_webhook_transport(
    monkeypatch,
):
    """
    The webhook subscription only ever targets settings.
    graph_mailbox_address (see graph_subscription_service.py's
    _create — it subscribes to that one mailbox's Inbox and no
    other), unlike the polling transport, which iterates several. So
    every message this route ever receives genuinely landed in that
    one mailbox, regardless of whether it appears in To, Cc, or is
    invisible in Bcc. Before this fix, only the polling transport
    passed landed_mailbox through — a Cc-only (or Bcc-only) match
    against the shared inbox delivered via a webhook fell through to
    "Unknown inbox address." This confirms _process_graph_notification
    now passes the configured mailbox through identically.
    """

    from app.ticketing.api import mail_integration

    settings = _base_settings(
        graph_webhook_client_state="secret",
        graph_mailbox_address="shared@example.com",
    )
    monkeypatch.setattr(mail_integration, "get_settings", lambda: settings)

    payload = IncomingMailPayload(
        internetMessageId="<msg-1@example.com>",
        subject="hello",
        from_=GraphRecipient(emailAddress=GraphEmailAddress(address="sender@example.com")),
        toRecipients=[
            GraphRecipient(emailAddress=GraphEmailAddress(address="someone-else@example.com"))
        ],
        body=GraphItemBody(contentType="text", content="hi"),
    )

    class _FakeMailProviderClient:
        async def fetch_message(self, message_id):
            return payload

    captured: dict = {}
    original_map = mail_integration.map_external_email_to_interaction

    def _spy_map(payload_arg, landed_mailbox=None):
        captured["landed_mailbox"] = landed_mailbox
        return original_map(payload_arg, landed_mailbox=landed_mailbox)

    monkeypatch.setattr(mail_integration, "map_external_email_to_interaction", _spy_map)

    class _FakeSession:
        async def commit(self):
            pass

        async def rollback(self):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr(mail_integration, "AsyncSessionLocal", lambda: _FakeSession())

    class _FakeEmailService:
        async def receive_email(self, email_request, files=None):
            captured["received"] = email_request

    monkeypatch.setattr(mail_integration, "_build_email_service", lambda db: _FakeEmailService())

    item = _notification_item("secret")

    await mail_integration._process_graph_notification(item, _FakeMailProviderClient())

    assert captured["landed_mailbox"] == "shared@example.com"
    assert captured["received"].landed_mailbox == "shared@example.com"


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


def test_build_graph_mail_provider_client_honors_explicit_mailbox_override(monkeypatch):
    """
    The multi-mailbox seam: an explicit mailbox_address must win over
    settings.graph_mailbox_address — this is what lets the same Graph
    identity (one auth_client) operate against a client-specific
    mailbox (the poller enumerating active clients' inbox_email, or
    outbound_dispatcher targeting a reply's own arrival mailbox)
    without needing a second configured identity.
    """

    monkeypatch.setattr(
        "app.ticketing.services.graph_auth.msal.ConfidentialClientApplication",
        lambda **kwargs: object(),
    )
    _cached_graph_auth_client.cache_clear()

    settings = _base_settings(
        graph_tenant_id="tenant-id-c",
        graph_client_id="client-id",
        graph_client_secret="client-secret",
        graph_mailbox_address="ticketing@probeps.com",
    )
    auth_client = build_graph_auth_client(settings)

    client = build_graph_mail_provider_client(
        settings, auth_client, mailbox_address="familyfirst@probeps.com"
    )

    assert client is not None
    assert client._mailbox_address == "familyfirst@probeps.com"


def test_get_mail_provider_client_threads_mailbox_override(monkeypatch):
    monkeypatch.setattr(
        "app.ticketing.services.graph_auth.msal.ConfidentialClientApplication",
        lambda **kwargs: object(),
    )
    _cached_graph_auth_client.cache_clear()

    settings = _base_settings(
        graph_tenant_id="tenant-id-d",
        graph_client_id="client-id",
        graph_client_secret="client-secret",
        graph_mailbox_address="ticketing@probeps.com",
    )

    client = get_mail_provider_client(settings, mailbox_address="familyfirst@probeps.com")

    assert client.__class__.__name__ == "GraphMailProviderClient"
    assert client._mailbox_address == "familyfirst@probeps.com"


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


def test_build_send_mail_message_omits_attachments_when_none():
    envelope = _envelope()

    message = _build_send_mail_message(envelope)

    assert "attachments" not in message


def test_build_send_mail_message_includes_attachments_as_graph_file_attachments():
    """
    Regression test for the real bug this session's fix addresses:
    attachments were uploaded/stored but never actually included in
    the outbound Graph sendMail call at all — a completely separate,
    silent gap from the In-Reply-To header bug above.
    """

    envelope = _envelope(
        attachments=[
            EnvelopeAttachment(
                filename="invoice.pdf",
                content_type="application/pdf",
                content_base64="aGVsbG8=",
            )
        ]
    )

    message = _build_send_mail_message(envelope)

    assert message["attachments"] == [
        {
            "@odata.type": "#microsoft.graph.fileAttachment",
            "name": "invoice.pdf",
            "contentType": "application/pdf",
            "contentBytes": "aGVsbG8=",
        }
    ]


# ---------------------------------------------------------
# Envelope -> Graph reply/replyAll body mapping (graph_client.py)
# ---------------------------------------------------------


def test_build_reply_action_body_uses_comment_for_agent_text():
    """
    Unlike sendMail (which puts the agent's text in `body`), the
    reply/replyAll action's own body-of-the-request uses `comment` —
    Graph prepends this above the quoted original message and handles
    the quoting/threading itself, which is what keeps the send inside
    the original Outlook/Gmail conversation. A plain, single-line body
    with no special characters passes through the HTML conversion
    (see the next test) unchanged, so this still holds for that case.
    """

    envelope = _envelope(reply_to_provider_message_id="AAMkAG-native-id")

    body = _build_reply_action_body(envelope)

    assert body["comment"] == envelope.body
    assert "body" not in body["message"]


def test_build_reply_action_body_converts_newlines_to_br_for_html_rendering():
    """
    Regression test for a real, live-confirmed bug: Graph's reply/
    replyAll `comment` parameter is always composed into an HTML body
    (confirmed against Microsoft's own Graph API docs — comment has no
    content-type option, unlike sendMail's message.body.contentType).
    A bare "\\n" has no meaning in HTML, so a multi-line signature sent
    as-is collapsed to one visual line for the recipient. `comment`
    must carry real <br> tags instead, and any literal HTML-special
    character in the agent's own text must be escaped first so it
    can't be misinterpreted once composited into HTML.
    """

    envelope = _envelope(
        reply_to_provider_message_id="AAMkAG-native-id",
        body="Regards,\nJane Doe\nAccount Manager & Co. <Probe>",
    )

    body = _build_reply_action_body(envelope)

    assert body["comment"] == (
        "Regards,<br>Jane Doe<br>Account Manager &amp; Co. &lt;Probe&gt;"
    )


def test_build_reply_action_body_overrides_recipients_explicitly():
    envelope = _envelope(
        reply_to_provider_message_id="AAMkAG-native-id",
        cc=["cc@example.com"],
        bcc=["bcc@example.com"],
    )

    body = _build_reply_action_body(envelope)

    assert body["message"]["toRecipients"] == [
        {"emailAddress": {"address": envelope.to_email}}
    ]
    assert body["message"]["ccRecipients"] == [{"emailAddress": {"address": "cc@example.com"}}]
    assert body["message"]["bccRecipients"] == [{"emailAddress": {"address": "bcc@example.com"}}]


def test_build_reply_action_body_omits_empty_cc_bcc():
    envelope = _envelope(reply_to_provider_message_id="AAMkAG-native-id")

    body = _build_reply_action_body(envelope)

    assert "ccRecipients" not in body["message"]
    assert "bccRecipients" not in body["message"]


def test_build_reply_action_body_includes_attachments_as_graph_file_attachments():
    envelope = _envelope(
        reply_to_provider_message_id="AAMkAG-native-id",
        attachments=[
            EnvelopeAttachment(
                filename="invoice.pdf",
                content_type="application/pdf",
                content_base64="aGVsbG8=",
            )
        ],
    )

    body = _build_reply_action_body(envelope)

    assert body["message"]["attachments"] == [
        {
            "@odata.type": "#microsoft.graph.fileAttachment",
            "name": "invoice.pdf",
            "contentType": "application/pdf",
            "contentBytes": "aGVsbG8=",
        }
    ]


async def test_send_email_dispatches_to_reply_endpoint_when_provider_message_id_set(monkeypatch):
    """
    The one branch point that decides Graph reply/replyAll vs.
    sendMail: envelope.reply_to_provider_message_id being set is what
    routes a send through the threaded reply action instead of
    sendMail — this is confirmed by intercepting the outbound httpx
    call itself, not just checking the pure message-building helpers
    above.
    """

    import app.ticketing.services.graph_client as graph_client_module

    captured: dict = {}

    class _FakeResponse:
        status_code = 202
        text = ""

    class _FakeAsyncClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc_info):
            return False

        async def post(self, url, headers=None, json=None):
            captured["url"] = url
            captured["json"] = json
            return _FakeResponse()

    monkeypatch.setattr(graph_client_module.httpx, "AsyncClient", lambda timeout=30.0: _FakeAsyncClient())

    client = graph_client_module.GraphMailProviderClient(
        auth_client=None,
        mailbox_address="mailbox@example.com",
        api_base_url="https://graph.microsoft.com/v1.0",
    )
    monkeypatch.setattr(client, "_authorized_headers", lambda: _fake_headers())

    envelope = _envelope(reply_to_provider_message_id="AAMkAG-native-id", reply_all=True)

    result = await client.send_email(envelope)

    assert captured["url"].endswith("/messages/AAMkAG-native-id/replyAll")
    assert captured["json"]["comment"] == envelope.body
    # replyAll returns 202 with no body — Graph hands back no real id
    # here, and envelope.message_id (this platform's own RFC
    # Message-ID) must never be substituted for one: a later reply
    # would pass it straight to Graph's reply/replyAll action, which
    # rejects a non-Graph id as malformed.
    assert result.provider_message_id is None
    assert result.status == "SENT"


async def test_send_email_dispatches_to_create_draft_then_send_when_no_reply_target(monkeypatch):
    """
    A brand-new Compose (no reply_to_provider_message_id) must NOT use
    sendMail — sendMail's 202-with-no-body response can never yield a
    real Graph id, which is exactly the bug that made a later
    Sent-Items reply fall back to unthreaded sendMail forever (see
    graph_client.py's send_email docstring). It must instead create a
    real draft (POST .../messages) and send that draft (POST
    .../messages/{id}/send), returning the draft's own real, resolvable
    id as provider_message_id.
    """

    import app.ticketing.services.graph_client as graph_client_module

    fake_client = _RecordingGraphHttpClient()
    monkeypatch.setattr(graph_client_module.httpx, "AsyncClient", lambda timeout=30.0, **_: fake_client)

    client = graph_client_module.GraphMailProviderClient(
        auth_client=None,
        mailbox_address="mailbox@example.com",
        api_base_url="https://graph.microsoft.com/v1.0",
    )
    monkeypatch.setattr(client, "_authorized_headers", lambda: _fake_headers())

    envelope = _envelope()  # reply_to_provider_message_id is None (Compose)

    result = await client.send_email(envelope)

    create_calls = [c for c in fake_client.calls if c["url"].endswith("/messages")]
    assert len(create_calls) == 1
    assert create_calls[0]["json"]["subject"] == envelope.subject

    send_calls = [c for c in fake_client.calls if c["url"].endswith("/send")]
    assert len(send_calls) == 1

    sendmail_calls = [c for c in fake_client.calls if c["url"].endswith("/sendMail")]
    assert sendmail_calls == []

    resolve_calls = [c for c in fake_client.calls if "/mailFolders/sentitems/messages" in c["url"]]
    assert len(resolve_calls) == 1

    # The resolved, real post-send Sent Items id — never the draft's
    # own id (which doesn't survive send on every mailbox this has
    # been confirmed against, see _send_via_draft's own comment), never
    # None, never this platform's own locally-generated RFC Message-ID.
    assert result.provider_message_id == fake_client.resolved_sent_id
    assert result.provider_message_id != fake_client.draft_id
    assert result.status == "SENT"


async def _fake_headers() -> dict:
    return {"Authorization": "Bearer test-token"}


class _FakeStorageService:
    """Minimal stand-in for StorageService — only download() is ever
    called by _add_large_attachment."""

    def __init__(self, data_by_key: dict[str, bytes]):
        self._data_by_key = data_by_key

    async def download(self, *, object_key: str) -> bytes:
        return self._data_by_key[object_key]


class _RecordingGraphHttpClient:
    """
    A single fake httpx.AsyncClient stand-in that serves every call
    _send_via_draft's methods make (create draft/reply, PATCH
    recipients, POST an attachment, POST createUploadSession, PUT
    upload chunks, POST send, and the GET that resolves the real
    post-send Sent Items id via conversationId) — routed purely by URL
    suffix/method, so one instance covers the whole multi-request flow
    the real upload-session/draft path requires (unlike the single-POST
    fast path the existing tests above only need).

    draft_id and resolved_sent_id are deliberately different strings —
    see _send_via_draft's own comment for why the draft's own id must
    never be trusted as the message's real post-send id; a test that
    let them collide could pass for the wrong reason.
    """

    def __init__(self):
        self.calls: list[dict] = []
        self.draft_id = "draft-123"
        self.conversation_id = "conv-abc"
        self.resolved_sent_id = "sent-item-456"
        self.upload_url = "https://upload.example.com/session-abc"

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    async def post(self, url, headers=None, json=None):
        self.calls.append({"method": "POST", "url": url, "headers": headers, "json": json})

        if url.endswith("/attachments/createUploadSession"):
            return _JsonResponse(200, {"uploadUrl": self.upload_url})
        if url.endswith("/send"):
            return _JsonResponse(202, {})
        if url.endswith("/attachments"):
            return _JsonResponse(201, {"id": "small-attachment-1"})
        if "/createReply" in url or "/createReplyAll" in url:
            return _JsonResponse(201, {"id": self.draft_id, "conversationId": self.conversation_id})
        if url.endswith("/messages"):
            return _JsonResponse(201, {"id": self.draft_id, "conversationId": self.conversation_id})

        raise AssertionError(f"unexpected POST {url}")

    async def get(self, url, headers=None):
        self.calls.append({"method": "GET", "url": url, "headers": headers})

        if "/mailFolders/sentitems/messages" in url and "conversationId" in url:
            assert self.conversation_id in url
            return _JsonResponse(200, {"value": [{"id": self.resolved_sent_id}]})

        raise AssertionError(f"unexpected GET {url}")

    async def patch(self, url, headers=None, json=None):
        self.calls.append({"method": "PATCH", "url": url, "headers": headers, "json": json})
        return _JsonResponse(200, {"id": self.draft_id})

    async def put(self, url, headers=None, content=None):
        self.calls.append({"method": "PUT", "url": url, "headers": headers, "content": content})
        assert headers is not None and "Authorization" not in headers, (
            "the upload-session URL is pre-authorized — no bearer token should "
            "be sent on the chunk PUTs"
        )
        return _JsonResponse(200, {})


class _JsonResponse:
    def __init__(self, status_code: int, body: dict):
        self.status_code = status_code
        self.text = str(body)
        self._body = body

    def json(self):
        return self._body


async def test_send_email_uses_upload_session_for_large_attachment_on_new_message(
    monkeypatch,
):
    """
    An attachment over the inline-embed threshold (GRAPH_INLINE_
    ATTACHMENT_MAX_BYTES, 3MB) must not be silently dropped (the
    pre-fix behavior) — it must go out via a real Graph draft +
    upload-session flow instead. Confirms the whole chain for a
    brand-new (non-reply) message: create draft -> upload session ->
    chunked PUTs covering every byte -> send.
    """

    import app.ticketing.services.graph_client as graph_client_module

    fake_client = _RecordingGraphHttpClient()
    monkeypatch.setattr(graph_client_module.httpx, "AsyncClient", lambda timeout=30.0, **_: fake_client)

    large_bytes = b"x" * (5 * 1024 * 1024)  # 5MB — over the 3MB inline threshold
    storage = _FakeStorageService({"attachments/big.pdf": large_bytes})

    client = graph_client_module.GraphMailProviderClient(
        auth_client=None,
        mailbox_address="mailbox@example.com",
        api_base_url="https://graph.microsoft.com/v1.0",
        storage_service=storage,
    )
    monkeypatch.setattr(client, "_authorized_headers", lambda: _fake_headers())

    envelope = _envelope(
        attachments=[
            EnvelopeAttachment(
                filename="big.pdf",
                content_type="application/pdf",
                storage_key="attachments/big.pdf",
                size_bytes=len(large_bytes),
            )
        ],
    )

    result = await client.send_email(envelope)

    assert result.provider_message_id == fake_client.resolved_sent_id
    assert result.status == "SENT"

    put_calls = [c for c in fake_client.calls if c["method"] == "PUT"]
    assert len(put_calls) == 2  # 5MB at a 4MB chunk size -> 4MB + 1MB

    total_uploaded = sum(len(c["content"]) for c in put_calls)
    assert total_uploaded == len(large_bytes)

    first_range = put_calls[0]["headers"]["Content-Range"]
    assert first_range == f"bytes 0-4194303/{len(large_bytes)}"
    second_range = put_calls[1]["headers"]["Content-Range"]
    assert second_range == f"bytes 4194304-{len(large_bytes) - 1}/{len(large_bytes)}"

    send_calls = [c for c in fake_client.calls if c["url"].endswith("/send")]
    assert len(send_calls) == 1


async def test_send_email_uses_upload_session_for_large_attachment_on_reply(monkeypatch):
    """
    Same as the new-message case, but for a reply: must create a real
    draft via createReply/createReplyAll (not the direct reply/
    replyAll action, which has no id to attach a large file to),
    explicitly override its recipients (createReply/createReplyAll
    auto-populate from the original message, which this platform's
    own resolved envelope must always win over), then attach and send.
    """

    import app.ticketing.services.graph_client as graph_client_module

    fake_client = _RecordingGraphHttpClient()
    monkeypatch.setattr(graph_client_module.httpx, "AsyncClient", lambda timeout=30.0, **_: fake_client)

    large_bytes = b"y" * (4 * 1024 * 1024)  # 4MB
    storage = _FakeStorageService({"attachments/scan.pdf": large_bytes})

    client = graph_client_module.GraphMailProviderClient(
        auth_client=None,
        mailbox_address="mailbox@example.com",
        api_base_url="https://graph.microsoft.com/v1.0",
        storage_service=storage,
    )
    monkeypatch.setattr(client, "_authorized_headers", lambda: _fake_headers())

    envelope = _envelope(
        reply_to_provider_message_id="AAMkAG-native-id",
        cc=["cc@example.com"],
        attachments=[
            EnvelopeAttachment(
                filename="scan.pdf",
                content_type="application/pdf",
                storage_key="attachments/scan.pdf",
                size_bytes=len(large_bytes),
            )
        ],
    )

    result = await client.send_email(envelope)

    assert result.provider_message_id == fake_client.resolved_sent_id

    create_reply_calls = [c for c in fake_client.calls if "/createReply" in c["url"]]
    assert len(create_reply_calls) == 1
    assert create_reply_calls[0]["json"] == {"comment": envelope.body}

    patch_calls = [c for c in fake_client.calls if c["method"] == "PATCH"]
    assert len(patch_calls) == 1
    assert patch_calls[0]["json"]["toRecipients"] == [
        {"emailAddress": {"address": envelope.to_email}}
    ]
    assert patch_calls[0]["json"]["ccRecipients"] == [
        {"emailAddress": {"address": "cc@example.com"}}
    ]
    assert patch_calls[0]["json"]["bccRecipients"] == []

    put_calls = [c for c in fake_client.calls if c["method"] == "PUT"]
    assert sum(len(c["content"]) for c in put_calls) == len(large_bytes)


async def test_send_email_uses_draft_path_for_small_attachment_when_no_reply_target(monkeypatch):
    """
    A brand-new Compose with only a small (already-inline,
    content_base64 set) attachment still has no reply_to_provider_
    message_id, so it takes the same create-draft-then-send path as
    the no-attachment case above (not the old single-POST sendMail
    path) — the attachment is added to the real draft via
    _add_small_attachment rather than inlined into a sendMail JSON
    body.
    """

    import app.ticketing.services.graph_client as graph_client_module

    fake_client = _RecordingGraphHttpClient()
    monkeypatch.setattr(graph_client_module.httpx, "AsyncClient", lambda timeout=30.0, **_: fake_client)

    client = graph_client_module.GraphMailProviderClient(
        auth_client=None,
        mailbox_address="mailbox@example.com",
        api_base_url="https://graph.microsoft.com/v1.0",
    )
    monkeypatch.setattr(client, "_authorized_headers", lambda: _fake_headers())

    envelope = _envelope(
        attachments=[
            EnvelopeAttachment(
                filename="small.pdf",
                content_type="application/pdf",
                content_base64="aGVsbG8=",
            )
        ],
    )

    result = await client.send_email(envelope)

    assert [c for c in fake_client.calls if c["url"].endswith("/sendMail")] == []
    attachment_calls = [c for c in fake_client.calls if c["url"].endswith("/attachments")]
    assert len(attachment_calls) == 1
    send_calls = [c for c in fake_client.calls if c["url"].endswith("/send")]
    assert len(send_calls) == 1
    assert result.provider_message_id == fake_client.resolved_sent_id


async def test_send_email_still_uses_reply_endpoint_for_small_attachment_with_known_reply_target(
    monkeypatch,
):
    """
    The one remaining fast path: a reply with an already-known real
    reply_to_provider_message_id and only small attachments must keep
    using Graph's direct reply/replyAll action (_send_reply, inline
    JSON attachments) rather than the create-draft-then-send path —
    that path is reserved for when there's no known target to reply
    against, or a large attachment forces it.
    """

    import app.ticketing.services.graph_client as graph_client_module

    captured: dict = {}

    class _FakeResponse:
        status_code = 202
        text = ""

    class _FakeAsyncClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc_info):
            return False

        async def post(self, url, headers=None, json=None):
            captured["url"] = url
            captured["json"] = json
            return _FakeResponse()

    monkeypatch.setattr(graph_client_module.httpx, "AsyncClient", lambda timeout=30.0: _FakeAsyncClient())

    client = graph_client_module.GraphMailProviderClient(
        auth_client=None,
        mailbox_address="mailbox@example.com",
        api_base_url="https://graph.microsoft.com/v1.0",
    )
    monkeypatch.setattr(client, "_authorized_headers", lambda: _fake_headers())

    envelope = _envelope(
        reply_to_provider_message_id="AAMkAG-native-id",
        attachments=[
            EnvelopeAttachment(
                filename="small.pdf",
                content_type="application/pdf",
                content_base64="aGVsbG8=",
            )
        ],
    )

    result = await client.send_email(envelope)

    assert captured["url"].endswith("/messages/AAMkAG-native-id/reply")
    # Graph's direct reply action also returns 202 with no body — no
    # real id for this reply's own send either (see _send_reply's own
    # comment for why that's fine: this codebase always replies
    # against the thread ROOT's id, never a reply's own).
    assert result.provider_message_id is None


# ---------------------------------------------------------------
# _resolve_sent_message_id — the fix for a real, empirically-confirmed
# bug: Graph's draft id does NOT survive send on every mailbox
# configuration (a shared mailbox sent via app-only permissions was
# observed handing the message a genuinely different id once it lands
# in Sent Items — GET on the pre-send draft id 404s afterward). This
# resolves the real post-send id via conversationId (confirmed stable
# across that same move) instead, with a short bounded retry for
# "not indexed yet" and a graceful None fallback on any failure.
# ---------------------------------------------------------------


async def test_resolve_sent_message_id_returns_none_when_conversation_id_is_none():
    import app.ticketing.services.graph_client as graph_client_module

    client = graph_client_module.GraphMailProviderClient(
        auth_client=None,
        mailbox_address="mailbox@example.com",
        api_base_url="https://graph.microsoft.com/v1.0",
    )

    result = await client._resolve_sent_message_id(None)

    assert result is None


async def test_resolve_sent_message_id_retries_then_finds_match(monkeypatch):
    """
    The first attempt finding nothing (Sent Items hasn't indexed the
    message yet) must not be treated as a final answer — it retries
    (with a short backoff, monkeypatched away here for test speed)
    until a match appears.
    """

    import app.ticketing.services.graph_client as graph_client_module

    monkeypatch.setattr(graph_client_module.asyncio, "sleep", _instant_sleep)

    call_count = 0

    class _FakeAsyncClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc_info):
            return False

        async def get(self, url, headers=None):
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                return _JsonResponse(200, {"value": []})
            return _JsonResponse(200, {"value": [{"id": "sent-item-789"}]})

    monkeypatch.setattr(graph_client_module.httpx, "AsyncClient", lambda timeout=30.0: _FakeAsyncClient())

    client = graph_client_module.GraphMailProviderClient(
        auth_client=None,
        mailbox_address="mailbox@example.com",
        api_base_url="https://graph.microsoft.com/v1.0",
    )
    monkeypatch.setattr(client, "_authorized_headers", lambda: _fake_headers())

    result = await client._resolve_sent_message_id("conv-xyz")

    assert result == "sent-item-789"
    assert call_count == 2


async def test_resolve_sent_message_id_returns_none_after_all_retries_exhausted(monkeypatch):
    import app.ticketing.services.graph_client as graph_client_module

    monkeypatch.setattr(graph_client_module.asyncio, "sleep", _instant_sleep)

    class _FakeAsyncClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc_info):
            return False

        async def get(self, url, headers=None):
            return _JsonResponse(200, {"value": []})

    monkeypatch.setattr(graph_client_module.httpx, "AsyncClient", lambda timeout=30.0: _FakeAsyncClient())

    client = graph_client_module.GraphMailProviderClient(
        auth_client=None,
        mailbox_address="mailbox@example.com",
        api_base_url="https://graph.microsoft.com/v1.0",
    )
    monkeypatch.setattr(client, "_authorized_headers", lambda: _fake_headers())

    result = await client._resolve_sent_message_id("conv-xyz")

    assert result is None


async def test_resolve_sent_message_id_returns_none_on_error_status(monkeypatch):
    import app.ticketing.services.graph_client as graph_client_module

    class _FakeAsyncClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc_info):
            return False

        async def get(self, url, headers=None):
            return _JsonResponse(403, {"error": {"code": "Forbidden"}})

    monkeypatch.setattr(graph_client_module.httpx, "AsyncClient", lambda timeout=30.0: _FakeAsyncClient())

    client = graph_client_module.GraphMailProviderClient(
        auth_client=None,
        mailbox_address="mailbox@example.com",
        api_base_url="https://graph.microsoft.com/v1.0",
    )
    monkeypatch.setattr(client, "_authorized_headers", lambda: _fake_headers())

    result = await client._resolve_sent_message_id("conv-xyz")

    assert result is None


async def _instant_sleep(*_args, **_kwargs) -> None:
    return None


async def test_fetch_message_attachments_builds_url_and_parses_response(monkeypatch):
    import app.ticketing.services.graph_client as graph_client_module

    captured: dict = {}

    class _FakeResponse:
        status_code = 200

        def json(self):
            return {
                "value": [
                    {
                        "@odata.type": "#microsoft.graph.fileAttachment",
                        "name": "invoice.pdf",
                        "contentType": "application/pdf",
                        "size": 1234,
                        "isInline": False,
                        "contentBytes": "aGVsbG8=",
                    }
                ]
            }

    class _FakeAsyncClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc_info):
            return False

        async def get(self, url, headers=None):
            captured["url"] = url
            return _FakeResponse()

    monkeypatch.setattr(graph_client_module.httpx, "AsyncClient", lambda timeout=30.0: _FakeAsyncClient())

    client = graph_client_module.GraphMailProviderClient(
        auth_client=None,
        mailbox_address="familyfirst@probeps.com",
        api_base_url="https://graph.microsoft.com/v1.0",
    )
    monkeypatch.setattr(client, "_authorized_headers", lambda: _fake_headers())

    attachments = await client.fetch_message_attachments("msg-id-123")

    assert captured["url"].endswith(
        "/users/familyfirst@probeps.com/messages/msg-id-123/attachments"
    )
    assert "$select" not in captured["url"]
    assert len(attachments) == 1
    assert attachments[0].name == "invoice.pdf"
    assert attachments[0].odata_type == "#microsoft.graph.fileAttachment"
    assert attachments[0].contentBytes == "aGVsbG8="


# ---------------------------------------------------------
# Graph attachment -> UploadFile mapping (mail_mapping_service.py)
# ---------------------------------------------------------


def _graph_attachment(**overrides) -> GraphAttachmentPayload:
    base = dict(
        # Real Graph responses omit @odata.type entirely once a
        # $select list is specified without naming it — None is the
        # realistic default, not the exact-match string a fully
        # cooperative Graph response would carry.
        odata_type=None,
        name="invoice.pdf",
        contentType="application/pdf",
        size=8,
        isInline=False,
        contentBytes="aGVsbG8=",  # base64("hello")
    )
    base.update(overrides)
    return GraphAttachmentPayload(**base)


def test_build_upload_files_from_graph_attachments_maps_real_file_attachment():
    files = build_upload_files_from_graph_attachments([_graph_attachment()])

    assert len(files) == 1
    assert files[0].filename == "invoice.pdf"
    assert files[0].content_type == "application/pdf"


async def test_build_upload_files_from_graph_attachments_content_readable():
    files = build_upload_files_from_graph_attachments([_graph_attachment()])

    content = await files[0].read()
    assert content == b"hello"


def test_build_upload_files_from_graph_attachments_keeps_non_image_inline_attachment():
    """
    A non-image inline attachment (this fixture defaults to a PDF) has
    nothing an HTML body's own <img src="cid:..."> could ever
    reference, but Graph's `isInline` flag is only a heuristic derived
    from the sender's own Content-Disposition header — real audio/
    voice attachments from voicemail systems, relays, and some mobile
    clients are routinely marked isInline with no cid: reference at
    all. Phase 4 fix: it's kept as a normal, non-inline, downloadable
    attachment (same outcome as if isInline had been False) instead of
    being dropped — unlike a genuine inline *image* (see
    test_build_upload_files_from_graph_attachments_keeps_inline_image
    below and the orphaned-inline-image case just after it), which
    still can't be kept since it has no other use once undisplayable.
    """

    files = build_upload_files_from_graph_attachments([_graph_attachment(isInline=True)])

    assert len(files) == 1
    assert files[0].filename == "invoice.pdf"
    assert files[0].is_inline is False
    assert files[0].content_id is None


def test_build_upload_files_from_graph_attachments_keeps_inline_audio():
    """
    Direct regression test for the reported production bug: an audio
    attachment (e.g. a voicemail/voice-memo) reported isInline=True by
    Graph with no contentId and no body cid: reference must still
    survive as a normal downloadable attachment, not vanish silently.
    """

    files = build_upload_files_from_graph_attachments(
        [
            _graph_attachment(
                name="voicemail.mp3",
                contentType="audio/mpeg",
                isInline=True,
                contentId=None,
            )
        ]
    )

    assert len(files) == 1
    assert files[0].filename == "voicemail.mp3"
    assert files[0].is_inline is False
    assert files[0].content_id is None


def test_build_upload_files_from_graph_attachments_keeps_inline_image():
    """
    Regression test for the primary screenshot-loss bug: Outlook
    represents a screenshot pasted directly into an email's body the
    same way it represents an embedded signature/logo image — a real
    fileAttachment with isInline=True and a contentId the body's own
    <img src="cid:..."> references. Dropping every isInline attachment
    (the old behavior) silently dropped every pasted screenshot too.
    """

    files = build_upload_files_from_graph_attachments(
        [
            _graph_attachment(
                name="image001.png",
                contentType="image/png",
                isInline=True,
                contentId="image001.png@01D9F2A1",
                contentBytes="aGVsbG8=",
            )
        ]
    )

    assert len(files) == 1
    assert files[0].filename == "image001.png"
    assert files[0].is_inline is True
    # Never re-minted — the body's own cid: reference must match this
    # exact Graph-assigned value for cid: resolution to work at all.
    assert files[0].content_id == "image001.png@01D9F2A1"


def test_build_upload_files_from_graph_attachments_drops_inline_image_with_no_content_id(caplog):
    """
    An isInline image with no contentId at all can never be referenced
    by any <img src="cid:..."> in the body — nothing to key display
    resolution off, so it's still dropped rather than stored as a
    silently-orphaned, never-displayed row.
    """

    with caplog.at_level(logging.WARNING):
        files = build_upload_files_from_graph_attachments(
            [_graph_attachment(contentType="image/png", isInline=True, contentId=None)]
        )

    assert files == []


def test_build_upload_files_from_graph_attachments_ordinary_attachment_has_no_content_id():
    """
    An ordinary (non-inline) attachment must never pick up is_inline/
    content_id — those stay exactly None/False, matching this
    function's byte-identical output for every attachment that existed
    before inline-image support.
    """

    files = build_upload_files_from_graph_attachments([_graph_attachment()])

    assert files[0].is_inline is False
    assert files[0].content_id is None


def test_build_upload_files_from_graph_attachments_drops_non_file_attachments(caplog):
    """
    An @odata.type that's explicitly present but not fileAttachment
    (e.g. a forwarded message attached as an item, or a reference
    attachment) must still be excluded — only a genuinely absent/None
    @odata.type is tolerated (see the accepts_real_graph_response_
    without_odata_type test below for that case).
    """

    with caplog.at_level(logging.WARNING):
        files = build_upload_files_from_graph_attachments(
            [_graph_attachment(odata_type="#microsoft.graph.itemAttachment")]
        )

    assert files == []
    assert "#microsoft.graph.itemAttachment" in caplog.text


def test_build_upload_files_from_graph_attachments_drops_missing_content(caplog):
    with caplog.at_level(logging.WARNING):
        files = build_upload_files_from_graph_attachments([_graph_attachment(contentBytes=None)])

    assert files == []
    assert "no contentBytes" in caplog.text


def test_build_upload_files_from_graph_attachments_accepts_real_graph_response_without_odata_type():
    """
    Regression test for the primary silent-drop bug: real Graph
    attachment responses omit @odata.type entirely (parses to None),
    which must no longer be treated as "not a file attachment."
    """

    files = build_upload_files_from_graph_attachments(
        [_graph_attachment(odata_type=None, isInline=False, contentBytes="aGVsbG8=")]
    )

    assert len(files) == 1
    assert files[0].filename == "invoice.pdf"


def test_build_upload_files_from_graph_attachments_accepts_generic_content_type():
    files = build_upload_files_from_graph_attachments(
        [_graph_attachment(contentType="application/octet-stream")]
    )

    assert len(files) == 1
    assert files[0].filename == "invoice.pdf"


def test_build_upload_files_from_graph_attachments_drops_unsupported_type():
    files = build_upload_files_from_graph_attachments(
        [_graph_attachment(name="malware.exe", contentType="application/x-msdownload")]
    )

    assert files == []


def test_build_upload_files_from_graph_attachments_caps_at_max_files():
    from app.ticketing.utils.constants import MAX_ATTACHMENT_FILES

    attachments = [
        _graph_attachment(name=f"file{i}.pdf") for i in range(MAX_ATTACHMENT_FILES + 3)
    ]

    files = build_upload_files_from_graph_attachments(attachments)

    assert len(files) == MAX_ATTACHMENT_FILES


# ---------------------------------------------------------
# build_upload_files_from_graph_attachments + html_body — regression
# coverage for the "logo sometimes renders inline, sometimes shows up
# as image001.jpg" bug: Graph's own `isInline` flag is an unreliable
# heuristic, so an attachment referenced by the body's own
# <img src="cid:..."> must be classified inline even when Graph
# reports isInline=False for it.
# ---------------------------------------------------------


def test_build_upload_files_from_graph_attachments_body_reference_classifies_inline_jpeg():
    html = '<p>Regards</p><img src="cid:image001.jpg@01D9F2A1">'

    files = build_upload_files_from_graph_attachments(
        [
            _graph_attachment(
                name="image001.jpg",
                contentType="image/jpeg",
                isInline=False,
                contentId="image001.jpg@01D9F2A1",
            )
        ],
        html,
    )

    assert len(files) == 1
    assert files[0].is_inline is True
    assert files[0].content_id == "image001.jpg@01D9F2A1"


def test_build_upload_files_from_graph_attachments_body_reference_classifies_inline_png():
    html = '<img src="cid:logo@company.example">'

    files = build_upload_files_from_graph_attachments(
        [
            _graph_attachment(
                name="logo.png",
                contentType="image/png",
                isInline=False,
                contentId="logo@company.example",
            )
        ],
        html,
    )

    assert len(files) == 1
    assert files[0].is_inline is True
    assert files[0].content_id == "logo@company.example"


def test_build_upload_files_from_graph_attachments_body_reference_ignores_filename_mismatch():
    """
    Matching is purely via the Content-ID <-> cid: relationship — a
    body img referencing a *different* cid than an attachment's own
    filename would suggest must still resolve correctly, and a
    completely different filename must not confuse the match.
    """

    html = '<img src="cid:abc123@example.com">'

    files = build_upload_files_from_graph_attachments(
        [
            _graph_attachment(
                name="unrelated-name.png",
                contentType="image/png",
                isInline=False,
                contentId="abc123@example.com",
            )
        ],
        html,
    )

    assert len(files) == 1
    assert files[0].is_inline is True
    assert files[0].content_id == "abc123@example.com"


def test_build_upload_files_from_graph_attachments_not_referenced_stays_a_genuine_attachment():
    """
    An attachment with a contentId that simply isn't mentioned in the
    body at all (isInline also False) must remain a normal,
    downloadable attachment — no regression from broadening
    classification to also consider the body.
    """

    html = "<p>No images referenced here.</p>"

    files = build_upload_files_from_graph_attachments(
        [
            _graph_attachment(
                name="photo.jpg",
                contentType="image/jpeg",
                isInline=False,
                contentId="photo123@example.com",
            )
        ],
        html,
    )

    assert len(files) == 1
    assert files[0].is_inline is False
    assert files[0].content_id is None


def test_build_upload_files_from_graph_attachments_case_and_bracket_insensitive_match():
    html = '<img src="CID:<Image001.JPG@01D9F2A1>">'

    files = build_upload_files_from_graph_attachments(
        [
            _graph_attachment(
                name="image001.jpg",
                contentType="image/jpeg",
                isInline=False,
                contentId="image001.jpg@01d9f2a1",
            )
        ],
        html,
    )

    assert len(files) == 1
    assert files[0].is_inline is True


def test_build_upload_files_from_graph_attachments_graph_content_id_brackets_are_preserved_raw():
    """
    Graph itself can report a bracketed contentId (some relays echo the
    raw MIME Content-ID header, brackets included, straight into this
    field) — matching against the body's own bracket-free cid: value
    must still succeed via _normalize_content_id, but the stored
    Attachment.content_id must keep Graph's original raw value exactly
    as reported, brackets and all. Frontend-side resolution of this
    exact mismatch shape is handled by richText.ts's own
    normalizeContentId, not here.
    """

    html = '<img src="cid:test-image@example.com">'

    files = build_upload_files_from_graph_attachments(
        [
            _graph_attachment(
                name="test-image.png",
                contentType="image/png",
                isInline=False,
                contentId="<test-image@example.com>",
            )
        ],
        html,
    )

    assert len(files) == 1
    assert files[0].is_inline is True
    assert files[0].content_id == "<test-image@example.com>"


def test_build_upload_files_from_graph_attachments_combined_content_id_mismatch_bracket_case_percent():
    """
    Stress _normalize_content_id across all three dimensions at once
    (bracketed + mixed-case + percent-encoded), beyond the existing
    single-dimension tests above (case_and_bracket_insensitive_match,
    percent_encoded_cid_reference_matches) — a real sender can combine
    all three in one message.
    """

    html = '<img src="CID:%3CLogo%40ReachMyDr.Example%3E">'

    files = build_upload_files_from_graph_attachments(
        [
            _graph_attachment(
                name="logo.png",
                contentType="image/png",
                isInline=False,
                contentId="logo@reachmydr.example",
            )
        ],
        html,
    )

    assert len(files) == 1
    assert files[0].is_inline is True
    assert files[0].content_id == "logo@reachmydr.example"


def test_build_upload_files_from_graph_attachments_generic_content_type_inline_image_by_extension():
    """
    Regression test for the ReachMyDr logo bug: a genuinely inline
    image whose sender/relay declared a generic contentType (Graph
    passes this through unchanged from the original message) must
    still be classified as an inline image — via its own filename
    extension against IMAGE_EXTENSIONS — or its content_id linkage to
    the body's own <img src="cid:..."> reference is lost and the
    frontend can never resolve it (see resolveCidImagesForDisplay in
    richText.ts, which falls back to "[image unavailable]" for any
    <img src="cid:..."> with no matching attachment content_id).
    """

    html = '<img src="cid:logo@reachmydr.example">'

    files = build_upload_files_from_graph_attachments(
        [
            _graph_attachment(
                name="logo.png",
                contentType="application/octet-stream",
                isInline=True,
                contentId="logo@reachmydr.example",
            )
        ],
        html,
    )

    assert len(files) == 1
    assert files[0].is_inline is True
    assert files[0].content_id == "logo@reachmydr.example"


def test_build_upload_files_from_graph_attachments_missing_content_type_inline_image_by_extension():
    """Same as above, but Graph/the sender omitted contentType entirely."""

    html = '<img src="cid:logo@reachmydr.example">'

    files = build_upload_files_from_graph_attachments(
        [
            _graph_attachment(
                name="logo.png",
                contentType=None,
                isInline=True,
                contentId="logo@reachmydr.example",
            )
        ],
        html,
    )

    assert len(files) == 1
    assert files[0].is_inline is True
    assert files[0].content_id == "logo@reachmydr.example"


def test_build_upload_files_from_graph_attachments_generic_content_type_non_image_stays_ordinary():
    """
    Control for the two tests above: the filename-extension fallback
    must never widen classification for a genuine non-image attachment
    that merely happens to also carry a generic contentType.
    """

    files = build_upload_files_from_graph_attachments(
        [_graph_attachment(name="invoice.pdf", contentType="application/octet-stream")]
    )

    assert len(files) == 1
    assert files[0].is_inline is False
    assert files[0].content_id is None


def test_build_upload_files_from_graph_attachments_percent_encoded_cid_reference_matches():
    """
    A sending client can percent-encode the cid: value inside the
    <img src="..."> attribute (e.g. "%40" for "@") even though Graph's
    own contentId field for the same attachment never is — the match
    must still succeed.
    """

    html = '<img src="cid:logo%40reachmydr.example">'

    files = build_upload_files_from_graph_attachments(
        [
            _graph_attachment(
                name="logo.png",
                contentType="image/png",
                isInline=False,
                contentId="logo@reachmydr.example",
            )
        ],
        html,
    )

    assert len(files) == 1
    assert files[0].is_inline is True
    assert files[0].content_id == "logo@reachmydr.example"


def test_build_upload_files_from_graph_attachments_multiple_inline_and_genuine_mixed():
    html = (
        '<img src="cid:logo1@x"><p>body</p><img src="cid:logo2@x">'
    )

    attachments = [
        _graph_attachment(
            name="logo1.png", contentType="image/png", isInline=False, contentId="logo1@x"
        ),
        _graph_attachment(
            name="logo2.png", contentType="image/png", isInline=True, contentId="logo2@x"
        ),
        _graph_attachment(
            name="report.pdf", contentType="application/pdf", isInline=False, contentId=None
        ),
    ]

    files = build_upload_files_from_graph_attachments(attachments, html)

    assert len(files) == 3
    by_name = {f.filename: f for f in files}
    assert by_name["logo1.png"].is_inline is True
    assert by_name["logo2.png"].is_inline is True
    assert by_name["report.pdf"].is_inline is False
    assert by_name["report.pdf"].content_id is None


def test_build_upload_files_from_graph_attachments_missing_html_body_falls_back_to_graph_isinline():
    """
    No html_body available at all (e.g. a plain-text message) must
    behave exactly as before this fix — classification falls back to
    Graph's own isInline flag alone.
    """

    files = build_upload_files_from_graph_attachments(
        [
            _graph_attachment(
                name="image001.jpg",
                contentType="image/jpeg",
                isInline=False,
                contentId="image001.jpg@01D9F2A1",
            )
        ]
    )

    assert len(files) == 1
    assert files[0].is_inline is False
    assert files[0].content_id is None


# ---------------------------------------------------------
# validate_attachment_type (validators.py) — extension is the real
# gate, declared content_type is advisory only
# ---------------------------------------------------------


def test_validate_attachment_type_tolerates_generic_content_type():
    extension = validate_attachment_type("invoice.pdf", "application/octet-stream")

    assert extension == "pdf"


def test_validate_attachment_type_tolerates_mismatched_content_type():
    extension = validate_attachment_type("photo.png", "application/octet-stream")

    assert extension == "png"


def test_validate_attachment_type_still_rejects_unsupported_extension():
    with pytest.raises(ValueError):
        validate_attachment_type("malware.exe", "application/octet-stream")


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
    # html_body is sanitized (the same choke point an agent-authored
    # outbound body_html already goes through — see html_sanitizer.py)
    # before storage, never the raw Graph HTML verbatim: the
    # unrecognized html/body wrapper tags are stripped (content kept),
    # and div's own dir attribute isn't in the sanitizer's allow-list.
    assert email.html_body == "<div>hello there</div>"


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
    assert email.html_body is not None
    assert 'src="cid:image1.png"' in email.html_body


def test_map_external_email_to_interaction_does_not_add_borders_to_nested_layout_tables():
    """
    Regression test for a real reported bug: a marketing/newsletter
    email (e.g. Sunshine Health) using nested <table> elements purely
    for layout rendered with visible rectangular borders around every
    layout container in UTMS, even though the original email had none.
    Root cause: mail_mapping_service used to sanitize inbound HTML
    through sanitize_outbound_html, which unconditionally forces
    border styling onto every <table>/<td>/<th> — correct for an
    agent's own pasted data table, wrong for an external sender's
    layout markup. Fixed by routing inbound HTML through the new
    sanitize_inbound_html instead, which shares the same
    tag/attribute/script-stripping allow-list but never adds borders.
    """

    nested_layout_html = (
        "<html><body>"
        "<table><tr><td>"
        "<table><tr><td>"
        "<table><tr><td>Sunshine Health — your monthly newsletter</td></tr></table>"
        "</td></tr></table>"
        "</td></tr></table>"
        "</body></html>"
    )
    payload = _graph_payload(nested_layout_html, "html")

    email = map_external_email_to_interaction(payload)

    assert email.html_body is not None
    assert "border" not in email.html_body
    assert "style=" not in email.html_body
    assert "Sunshine Health" in email.html_body
    assert email.html_body.count("<table>") == 3


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


def test_map_external_email_to_interaction_propagates_cc_and_to_recipients():
    """
    Backs Reply-All: the original message's Cc list and full To list
    both need to survive the Graph -> EmailRequest mapping, not just
    the single arrival address `to_email` already captured.
    """

    payload = _graph_payload("hello", "text")
    payload.toRecipients.append(
        GraphRecipient(emailAddress=GraphEmailAddress(address="colleague@client.com"))
    )
    payload.ccRecipients = [
        GraphRecipient(emailAddress=GraphEmailAddress(address="cc1@client.com")),
        GraphRecipient(emailAddress=GraphEmailAddress(address="cc2@client.com")),
    ]

    email = map_external_email_to_interaction(payload)

    assert email.cc == ["cc1@client.com", "cc2@client.com"]
    assert email.to_recipients == ["ticketing@probeps.com", "colleague@client.com"]


def test_map_external_email_to_interaction_cc_and_to_recipients_empty_by_default():
    payload = _graph_payload("hello", "text")

    email = map_external_email_to_interaction(payload)

    assert email.cc == []
    assert email.to_recipients == ["ticketing@probeps.com"]


def test_map_external_email_to_interaction_sanitizes_dangerous_inbound_html():
    """
    An inbound sender's raw HTML is no more trustworthy than an
    agent-authored paste — a script tag/event-handler attribute must
    never survive into the stored html_body that the Mail/Ticket UI
    later renders via dangerouslySetInnerHTML.
    """

    payload = _graph_payload(
        '<p onclick="evil()">hi</p><script>alert(1)</script>', "html"
    )

    email = map_external_email_to_interaction(payload)

    assert email.html_body is not None
    assert "<script" not in email.html_body
    assert "onclick" not in email.html_body
    assert "<p>hi</p>" in email.html_body


def test_map_external_email_to_interaction_preserves_a_real_table():
    """
    A genuine 2x2 inbound data table must both survive structurally
    and now get the same visible-grid border styling an agent-authored
    table gets, via sanitize_inbound_html's shape-based classifier
    (_is_genuine_data_table) — the fix for the "genuine inbound tables
    never got borders" half of the table-border regression. This is
    deliberately the opposite shape from the nested-layout-table
    regression test above (2 rows x 2 columns vs 1x1-per-level nesting)
    so the two tests can never be satisfied by the same broken logic.
    """

    payload = _graph_payload(
        "<table><tbody><tr><td>Name</td><td>Status</td></tr>"
        "<tr><td>Raju</td><td>Open</td></tr></tbody></table>",
        "html",
    )

    email = map_external_email_to_interaction(payload)

    assert email.html_body is not None
    assert "<table" in email.html_body
    assert "border-collapse:collapse" in email.html_body
    assert "border:1px solid" in email.html_body
    assert "<td>Raju</td>" not in email.html_body  # styled now, not the bare tag
    assert "Raju</td>" in email.html_body
    assert "Status</td>" in email.html_body


def test_map_external_email_to_interaction_passes_through_landed_mailbox():
    # landed_mailbox is the Graph-poller-only signal for which mailbox
    # this payload was actually fetched from (see
    # graph_mail_poller.py's _poll_one_mailbox and
    # EmailRequest.landed_mailbox's own docstring) — confirms the
    # mapping function forwards it onto EmailRequest untouched.
    payload = _graph_payload("hello", "text")

    email = map_external_email_to_interaction(
        payload, landed_mailbox="credentialing@probeps.com"
    )

    assert email.landed_mailbox == "credentialing@probeps.com"


def test_map_external_email_to_interaction_landed_mailbox_none_by_default():
    # Every non-poller caller (the webhook transport, tests predating
    # this parameter) omits landed_mailbox entirely — must stay None,
    # not default to some inferred value, so EmailService.receive_email
    # correctly falls back to its original to_email-based resolution.
    payload = _graph_payload("hello", "text")

    email = map_external_email_to_interaction(payload)

    assert email.landed_mailbox is None
    assert "<table" in email.html_body
    assert "Raju</td>" in email.html_body
    assert "Status</td>" in email.html_body
