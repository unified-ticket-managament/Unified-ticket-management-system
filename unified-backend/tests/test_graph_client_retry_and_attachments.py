# test_graph_client_retry_and_attachments.py
#
# Pure-logic coverage for two P1 pieces layered onto graph_client.py —
# no DB, no real network call:
#
# 1. Retry-policy wiring: confirms the three true send actions
#    (sendMail here; _send_reply/_send_draft share the exact same
#    call_with_graph_retry wiring) never retry a 5xx/transport error
#    but do retry a 429, while a safe/idempotent call (fetch_message_
#    attachments here) retries a 5xx into an eventual success — see
#    graph_retry.py's own module docstring for the policy split, and
#    test_graph_retry.py for the wrapper's own exhaustive unit tests.
# 2. itemAttachment ($value) resolution into a downloadable .eml, and
#    winmail.dat/TNEF passthrough — see graph_client._resolve_item_
#    attachments and mail_mapping_service.build_upload_files_from_
#    graph_attachments.

import base64

import httpx
import pytest

from app.ticketing.schemas.mail_integration import GraphAttachmentPayload
from app.ticketing.schemas.payloads import OutboundEnvelope
from app.ticketing.services.graph_client import GraphAPIError, GraphMailProviderClient
from app.ticketing.services.mail_mapping_service import build_upload_files_from_graph_attachments


async def _fake_headers() -> dict:
    return {"Authorization": "Bearer test-token"}


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


def _client(monkeypatch) -> GraphMailProviderClient:
    client = GraphMailProviderClient(
        auth_client=None,
        mailbox_address="mailbox@example.com",
        api_base_url="https://graph.microsoft.com/v1.0",
    )
    monkeypatch.setattr(client, "_authorized_headers", lambda: _fake_headers())
    monkeypatch.setattr(client, "_force_refresh_token", lambda: _noop())
    return client


async def _noop():
    return None


def _mock_backoff_sleep(monkeypatch):
    async def _fake_sleep(seconds):
        return None

    monkeypatch.setattr("app.ticketing.services.graph_retry.asyncio.sleep", _fake_sleep)


class _FakeResponse:
    def __init__(self, status_code: int, body=None, text: str = "", content: bytes = b""):
        self.status_code = status_code
        self._body = body if body is not None else {}
        self.text = text or str(self._body)
        self.content = content
        self.headers: dict = {}

    def json(self):
        return self._body


class _QueuedGraphHttpClient:
    """A fake httpx.AsyncClient stand-in whose get/post return one
    queued response per call, keyed by HTTP method — lets a test
    script an exact sequence (e.g. 500 then 200) across the retry
    wrapper's successive attempts."""

    def __init__(self, *, posts=None, gets=None):
        self._posts = list(posts or [])
        self._gets = list(gets or [])
        self.post_calls: list[dict] = []
        self.get_calls: list[dict] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    async def post(self, url, headers=None, json=None):
        self.post_calls.append({"url": url, "json": json})
        item = self._posts.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    async def get(self, url, headers=None):
        self.get_calls.append({"url": url})
        item = self._gets.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


# ---------------------------------------------------------
# 1. Retry-policy wiring
# ---------------------------------------------------------


async def test_send_mail_does_not_retry_a_5xx(monkeypatch):
    import app.ticketing.services.graph_client as graph_client_module

    fake = _QueuedGraphHttpClient(posts=[_FakeResponse(500, text="boom")])
    monkeypatch.setattr(graph_client_module.httpx, "AsyncClient", lambda timeout=30.0, **_: fake)

    client = _client(monkeypatch)

    with pytest.raises(GraphAPIError) as exc_info:
        await client.send_email(_envelope())

    assert exc_info.value.status_code == 500
    assert len(fake.post_calls) == 1  # no retry attempted


async def test_send_mail_does_not_retry_a_transport_error(monkeypatch):
    import app.ticketing.services.graph_client as graph_client_module

    fake = _QueuedGraphHttpClient(posts=[httpx.ConnectError("boom")])
    monkeypatch.setattr(graph_client_module.httpx, "AsyncClient", lambda timeout=30.0, **_: fake)

    client = _client(monkeypatch)

    with pytest.raises(httpx.ConnectError):
        await client.send_email(_envelope())

    assert len(fake.post_calls) == 1


async def test_send_mail_retries_a_429_into_success(monkeypatch):
    import app.ticketing.services.graph_client as graph_client_module

    _mock_backoff_sleep(monkeypatch)
    fake = _QueuedGraphHttpClient(posts=[_FakeResponse(429), _FakeResponse(202)])
    monkeypatch.setattr(graph_client_module.httpx, "AsyncClient", lambda timeout=30.0, **_: fake)

    client = _client(monkeypatch)

    result = await client.send_email(_envelope())

    assert result.status == "SENT"
    assert len(fake.post_calls) == 2


async def test_fetch_message_attachments_retries_a_5xx_into_success(monkeypatch):
    import app.ticketing.services.graph_client as graph_client_module

    _mock_backoff_sleep(monkeypatch)
    fake = _QueuedGraphHttpClient(
        gets=[_FakeResponse(503), _FakeResponse(200, body={"value": []})]
    )
    monkeypatch.setattr(graph_client_module.httpx, "AsyncClient", lambda timeout=30.0, **_: fake)

    client = _client(monkeypatch)

    result = await client.fetch_message_attachments("msg-1")

    assert result == []
    assert len(fake.get_calls) == 2  # the safe policy retried the 503


# ---------------------------------------------------------
# 2. itemAttachment ($value) resolution + winmail.dat passthrough
# ---------------------------------------------------------


async def test_item_attachment_is_resolved_into_a_downloadable_eml(monkeypatch):
    import app.ticketing.services.graph_client as graph_client_module

    raw_mime_bytes = b"From: a@example.com\r\nSubject: fwd\r\n\r\nbody"
    attachments_list_response = _FakeResponse(
        200,
        body={
            "value": [
                {
                    "@odata.type": "#microsoft.graph.itemAttachment",
                    "id": "attachment-1",
                    "name": "Fwd: original message",
                }
            ]
        },
    )
    value_response = _FakeResponse(200, content=raw_mime_bytes)

    fake = _QueuedGraphHttpClient(gets=[attachments_list_response, value_response])
    monkeypatch.setattr(graph_client_module.httpx, "AsyncClient", lambda timeout=30.0, **_: fake)

    client = _client(monkeypatch)

    result = await client.fetch_message_attachments("msg-1")

    assert len(result) == 1
    resolved = result[0]
    assert resolved.name.endswith(".eml")
    assert resolved.contentType == "message/rfc822"
    assert base64.b64decode(resolved.contentBytes) == raw_mime_bytes

    # And the mapping layer (previously dropped every itemAttachment
    # unconditionally) now lets this resolved one through.
    files = build_upload_files_from_graph_attachments(result)
    assert len(files) == 1
    assert files[0].filename.endswith(".eml")


async def test_unresolvable_item_attachment_is_left_dropped_same_as_before(monkeypatch):
    import app.ticketing.services.graph_client as graph_client_module

    attachments_list_response = _FakeResponse(
        200,
        body={
            "value": [
                {
                    "@odata.type": "#microsoft.graph.itemAttachment",
                    "id": "attachment-1",
                    "name": "Fwd: original message",
                }
            ]
        },
    )
    # The $value fetch fails outright (e.g. a genuinely unresolvable
    # nested message) — best-effort: logged, left without
    # contentBytes, no exception raised.
    value_response = _FakeResponse(404, text="not found")

    fake = _QueuedGraphHttpClient(gets=[attachments_list_response, value_response])
    monkeypatch.setattr(graph_client_module.httpx, "AsyncClient", lambda timeout=30.0, **_: fake)

    client = _client(monkeypatch)

    result = await client.fetch_message_attachments("msg-1")

    assert len(result) == 1
    assert result[0].contentBytes is None

    files = build_upload_files_from_graph_attachments(result)
    assert files == []  # still dropped downstream, exactly as before this feature


def test_winmail_dat_passes_the_attachment_allow_list():
    payload = GraphAttachmentPayload(
        **{
            "@odata.type": "#microsoft.graph.fileAttachment",
            "name": "winmail.dat",
            "contentType": "application/ms-tnef",
            "contentBytes": base64.b64encode(b"opaque-tnef-bytes").decode("ascii"),
        }
    )

    files = build_upload_files_from_graph_attachments([payload])

    assert len(files) == 1
    assert files[0].filename == "winmail.dat"
    assert files[0].content_type == "application/ms-tnef"
