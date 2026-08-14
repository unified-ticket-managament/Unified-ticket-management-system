# test_graph_email_sender.py
#
# Pure-logic coverage for GraphEmailSender (app/core/email_sender.py)
# and get_email_sender()'s Graph-first factory logic — no DB, no real
# network call to Graph or Azure AD. Mirrors test_graph_mail_integration
# .py's own mocking conventions (fake httpx.AsyncClient, _base_settings
# with _env_file=None) since this is the same Graph auth seam reused
# for a different transport.

import pytest

import app.core.email_sender as email_sender_module
from app.core.config import Settings
from app.core.email_sender import (
    GraphEmailSender,
    LoggingEmailSender,
    SMTPEmailSender,
    get_email_sender,
)
from app.ticketing.services.graph_auth import _cached_graph_auth_client


def _base_settings(**overrides) -> Settings:
    """
    Same isolation rationale as test_graph_mail_integration.py's own
    helper: _env_file=None keeps this from ever reading the real
    unified-backend/.env (which has real Graph credentials configured
    for ticketing@probeps.com) — every test here must go through this
    helper, not Settings() directly.
    """

    return Settings(
        _env_file=None,
        database_url="postgresql+asyncpg://user:pass@localhost/test",
        jwt_secret_key="test-secret",
        sla_sweep_shared_secret="test-sweep-secret",
        **overrides,
    )


class _FakeAuthClient:
    def __init__(self, *, token: str = "test-token", should_raise: bool = False):
        self._token = token
        self._should_raise = should_raise

    async def get_token(self) -> str:
        if self._should_raise:
            raise RuntimeError("token acquisition failed")
        return self._token


class _FakeResponse:
    def __init__(self, status_code: int = 202, text: str = ""):
        self.status_code = status_code
        self.text = text


class _FakeAsyncClient:
    def __init__(self, response: _FakeResponse, captured: dict):
        self._response = response
        self._captured = captured

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    async def post(self, url, headers=None, json=None):
        self._captured["url"] = url
        self._captured["headers"] = headers
        self._captured["json"] = json
        return self._response


# ---------------------------------------
# GraphEmailSender.send()
# ---------------------------------------


async def test_graph_email_sender_sends_html_when_html_body_given(monkeypatch):
    captured: dict = {}
    monkeypatch.setattr(
        email_sender_module.httpx,
        "AsyncClient",
        lambda timeout=30.0: _FakeAsyncClient(_FakeResponse(202), captured),
    )

    sender = GraphEmailSender(
        auth_client=_FakeAuthClient(token="tok-123"),
        mailbox_address="ticketing@probeps.com",
        api_base_url="https://graph.microsoft.com/v1.0",
    )

    result = await sender.send(
        to_email="agent@company.com",
        subject="A ticket was assigned to you",
        body="plain text body",
        html_body="<p>html body</p>",
    )

    assert result is True
    assert captured["url"] == "https://graph.microsoft.com/v1.0/users/ticketing@probeps.com/sendMail"
    assert captured["headers"] == {"Authorization": "Bearer tok-123"}
    message = captured["json"]["message"]
    assert message["subject"] == "A ticket was assigned to you"
    assert message["body"] == {"contentType": "HTML", "content": "<p>html body</p>"}
    assert message["toRecipients"] == [{"emailAddress": {"address": "agent@company.com"}}]
    assert captured["json"]["saveToSentItems"] is True


async def test_graph_email_sender_sends_text_when_no_html_body(monkeypatch):
    captured: dict = {}
    monkeypatch.setattr(
        email_sender_module.httpx,
        "AsyncClient",
        lambda timeout=30.0: _FakeAsyncClient(_FakeResponse(202), captured),
    )

    sender = GraphEmailSender(
        auth_client=_FakeAuthClient(),
        mailbox_address="ticketing@probeps.com",
        api_base_url="https://graph.microsoft.com/v1.0",
    )

    result = await sender.send(to_email="agent@company.com", subject="s", body="plain only")

    assert result is True
    assert captured["json"]["message"]["body"] == {"contentType": "Text", "content": "plain only"}


async def test_graph_email_sender_returns_false_on_non_202(monkeypatch):
    captured: dict = {}
    monkeypatch.setattr(
        email_sender_module.httpx,
        "AsyncClient",
        lambda timeout=30.0: _FakeAsyncClient(_FakeResponse(403, "Authorization_RequestDenied"), captured),
    )

    sender = GraphEmailSender(
        auth_client=_FakeAuthClient(),
        mailbox_address="ticketing@probeps.com",
        api_base_url="https://graph.microsoft.com/v1.0",
    )

    result = await sender.send(to_email="agent@company.com", subject="s", body="b")

    assert result is False


async def test_graph_email_sender_returns_false_on_token_failure_without_raising():
    sender = GraphEmailSender(
        auth_client=_FakeAuthClient(should_raise=True),
        mailbox_address="ticketing@probeps.com",
        api_base_url="https://graph.microsoft.com/v1.0",
    )

    # Must not raise — a token/transport failure is caught and logged,
    # never propagated to the caller (dispatch_notification_emails
    # relies on this exact contract).
    result = await sender.send(to_email="agent@company.com", subject="s", body="b")

    assert result is False


# ---------------------------------------
# get_email_sender() factory — Graph-first, SMTP/logging fallback
# ---------------------------------------


def test_get_email_sender_returns_graph_when_fully_configured(monkeypatch):
    monkeypatch.setattr(
        "app.ticketing.services.graph_auth.msal.ConfidentialClientApplication",
        lambda **kwargs: object(),
    )
    _cached_graph_auth_client.cache_clear()

    settings = _base_settings(
        graph_tenant_id="tenant-id",
        graph_client_id="client-id",
        graph_client_secret="client-secret",
        graph_mailbox_address="ticketing@probeps.com",
    )
    monkeypatch.setattr(email_sender_module, "get_settings", lambda: settings)

    sender = get_email_sender()

    assert isinstance(sender, GraphEmailSender)
    assert sender._mailbox_address == "ticketing@probeps.com"


def test_get_email_sender_falls_back_to_smtp_when_graph_not_configured(monkeypatch):
    settings = _base_settings(smtp_host="smtp.example.com")
    monkeypatch.setattr(email_sender_module, "get_settings", lambda: settings)

    sender = get_email_sender()

    assert isinstance(sender, SMTPEmailSender)


def test_get_email_sender_falls_back_to_logging_when_nothing_configured(monkeypatch):
    settings = _base_settings()
    monkeypatch.setattr(email_sender_module, "get_settings", lambda: settings)

    sender = get_email_sender()

    assert isinstance(sender, LoggingEmailSender)


def test_get_email_sender_prefers_graph_over_smtp_when_both_configured(monkeypatch):
    monkeypatch.setattr(
        "app.ticketing.services.graph_auth.msal.ConfidentialClientApplication",
        lambda **kwargs: object(),
    )
    _cached_graph_auth_client.cache_clear()

    settings = _base_settings(
        graph_tenant_id="tenant-id",
        graph_client_id="client-id",
        graph_client_secret="client-secret",
        graph_mailbox_address="ticketing@probeps.com",
        smtp_host="smtp.example.com",
    )
    monkeypatch.setattr(email_sender_module, "get_settings", lambda: settings)

    sender = get_email_sender()

    assert isinstance(sender, GraphEmailSender)
