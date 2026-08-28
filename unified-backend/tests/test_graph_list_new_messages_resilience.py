# test_graph_list_new_messages_resilience.py
#
# P0 regression guard: GraphMailProviderClient.list_new_messages used
# to build its return value via a single list comprehension
# (`[IncomingMailPayload.model_validate(item) for item in items]`) —
# one Graph-returned message failing that schema (e.g. an empty
# toRecipients on a Bcc-only delivery) raised out of the whole call,
# which the poller's blanket `except Exception` caught *before* the
# per-message loop even started. The mailbox's checkpoint was never
# advanced, so the next tick re-fetched the exact same poison message
# and failed identically — a permanent, silent inbound outage for that
# mailbox. Fixed by validating each item individually and skipping
# (logging) only the ones that fail, never the whole batch.

from datetime import datetime, timezone

import httpx
import pytest

from app.ticketing.services import graph_client as graph_client_module
from app.ticketing.services.graph_client import GraphMailProviderClient


class _FakeAuthClient:
    async def get_token(self, force_refresh: bool = False) -> str:
        return "fake-token"


class _FakeResponse:
    def __init__(self, payload: dict):
        self.status_code = 200
        self._payload = payload
        self.text = "ok"

    def json(self) -> dict:
        return self._payload


class _FakeAsyncClient:
    def __init__(self, response: _FakeResponse, **kwargs):
        self._response = response

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    async def get(self, url: str, headers: dict) -> httpx.Response:
        return self._response


def _valid_graph_item(message_id: str) -> dict:
    return {
        "internetMessageId": message_id,
        "subject": "A real message",
        "from": {"emailAddress": {"name": "Sender", "address": "sender@example.com"}},
        "toRecipients": [{"emailAddress": {"address": "inbox@example.com"}}],
        "body": {"contentType": "text", "content": "hello"},
    }


def _malformed_graph_item() -> dict:
    # Missing internetMessageId (required, min_length=1) and
    # toRecipients (required, min_length=1) — a real shape Graph can
    # return for a Bcc-only or legacy-relay message.
    return {
        "id": "AAMk-poison",
        "subject": "A message with no recognizable recipients",
        "from": {"emailAddress": {"name": "Sender", "address": "sender@example.com"}},
        "toRecipients": [],
        "body": {"contentType": "text", "content": "hello"},
    }


@pytest.fixture(autouse=True)
def _no_real_retry(monkeypatch):
    # Bypass the real retry/backoff machinery entirely — this test is
    # about per-item validation resilience, not Graph retry policy —
    # by calling `attempt()` exactly once and returning its result.
    async def _fake_call_with_graph_retry(attempt, **kwargs):
        return await attempt()

    monkeypatch.setattr(
        graph_client_module, "call_with_graph_retry", _fake_call_with_graph_retry
    )


async def test_one_malformed_message_does_not_fail_the_whole_batch(monkeypatch):
    payload = {"value": [_valid_graph_item("<good-1@example.com>"), _malformed_graph_item()]}
    response = _FakeResponse(payload)

    monkeypatch.setattr(
        graph_client_module.httpx,
        "AsyncClient",
        lambda **kwargs: _FakeAsyncClient(response, **kwargs),
    )

    client = GraphMailProviderClient(
        auth_client=_FakeAuthClient(),
        mailbox_address="inbox@example.com",
        api_base_url="https://graph.example.test/v1.0",
    )

    messages = await client.list_new_messages(since=datetime.now(timezone.utc))

    assert len(messages) == 1
    assert messages[0].internetMessageId == "<good-1@example.com>"


async def test_all_malformed_returns_empty_list_not_an_exception(monkeypatch):
    payload = {"value": [_malformed_graph_item(), _malformed_graph_item()]}
    response = _FakeResponse(payload)

    monkeypatch.setattr(
        graph_client_module.httpx,
        "AsyncClient",
        lambda **kwargs: _FakeAsyncClient(response, **kwargs),
    )

    client = GraphMailProviderClient(
        auth_client=_FakeAuthClient(),
        mailbox_address="inbox@example.com",
        api_base_url="https://graph.example.test/v1.0",
    )

    messages = await client.list_new_messages(since=datetime.now(timezone.utc))

    assert messages == []


class _FakeSequentialAsyncClient:
    """Returns one _FakeResponse per call to .get(), in order — models
    Graph handing back a chain of @odata.nextLink pages, unlike
    _FakeAsyncClient above which always returns the same response
    regardless of how many times it's called."""

    _responses: list[_FakeResponse] = []
    call_count = 0

    def __init__(self, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    async def get(self, url: str, headers: dict) -> httpx.Response:
        response = type(self)._responses[type(self).call_count]
        type(self).call_count += 1
        return response


def _install_sequential_responses(monkeypatch, responses: list[_FakeResponse]):
    fake_cls = type(
        "_FakeSequentialAsyncClientInstance", (_FakeSequentialAsyncClient,), {}
    )
    fake_cls._responses = responses
    fake_cls.call_count = 0
    monkeypatch.setattr(
        graph_client_module.httpx, "AsyncClient", lambda **kwargs: fake_cls(**kwargs)
    )
    return fake_cls


async def test_follows_odata_next_link_across_pages(monkeypatch):
    page_1 = _FakeResponse(
        {
            "value": [_valid_graph_item("<page1-1@example.com>")],
            "@odata.nextLink": "https://graph.example.test/v1.0/users/inbox@example.com/mailFolders('Inbox')/messages?$skip=50",
        }
    )
    page_2 = _FakeResponse({"value": [_valid_graph_item("<page2-1@example.com>")]})

    fake_cls = _install_sequential_responses(monkeypatch, [page_1, page_2])

    client = GraphMailProviderClient(
        auth_client=_FakeAuthClient(),
        mailbox_address="inbox@example.com",
        api_base_url="https://graph.example.test/v1.0",
    )

    messages = await client.list_new_messages(since=datetime.now(timezone.utc))

    assert fake_cls.call_count == 2
    assert {m.internetMessageId for m in messages} == {
        "<page1-1@example.com>",
        "<page2-1@example.com>",
    }


async def test_stops_at_page_cap_with_nextlink_still_present(monkeypatch):
    # Every page still reports a further @odata.nextLink — without a
    # cap this would loop forever.
    page = _FakeResponse(
        {
            "value": [_valid_graph_item("<looping@example.com>")],
            "@odata.nextLink": "https://graph.example.test/v1.0/users/inbox@example.com/mailFolders('Inbox')/messages?$skip=50",
        }
    )

    fake_cls = _install_sequential_responses(
        monkeypatch, [page] * graph_client_module.MAX_LIST_MESSAGES_PAGES
    )

    client = GraphMailProviderClient(
        auth_client=_FakeAuthClient(),
        mailbox_address="inbox@example.com",
        api_base_url="https://graph.example.test/v1.0",
    )

    messages = await client.list_new_messages(since=datetime.now(timezone.utc))

    assert fake_cls.call_count == graph_client_module.MAX_LIST_MESSAGES_PAGES
    assert len(messages) == graph_client_module.MAX_LIST_MESSAGES_PAGES
