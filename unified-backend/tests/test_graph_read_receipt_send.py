# test_graph_read_receipt_send.py
#
# Outbound side of the Outlook-style read-receipt feature, against a
# fully fake httpx client (no network):
#
# - isReadReceiptRequested is sent ONLY when requested, in the right
#   place (new draft body; reply-draft PATCH — never the createReply
#   body), and Graph's rejected internetMessageHeaders is never used;
# - a receipt-requested reply goes createReply/createReplyAll -> PATCH
#   -> send and NEVER the direct /reply or /replyAll action (202, no id);
# - the REAL internetMessageId is taken from the create response (no
#   Sent-Items/timestamp/conversation inference), per message, even for
#   rapid replies in one conversation;
# - unflagged sends keep their historical route and payload;
# - the provider contract is shared by the Graph and mock providers;
# - the inbound fetch sites ask Graph for the item class.

from datetime import datetime, timezone

import pytest

from app.ticketing.schemas.payloads import OutboundEnvelope
from app.ticketing.services import graph_client as graph_client_module
from app.ticketing.services.graph_client import (
    MESSAGE_ITEM_CLASS_EXPAND,
    GraphAPIError,
    GraphMailProviderClient,
    _build_reply_action_body,
    _build_send_mail_message,
)
from app.ticketing.services.mail_provider import (
    MailProviderClient,
    MockMailProviderClient,
)


def _envelope(**overrides) -> OutboundEnvelope:
    base = dict(
        from_email="clientinbox@example.com",
        to_email="patient@example.com",
        subject="Re: Test",
        message_id="<local-placeholder@example.com>",
        body="Hello there.",
    )
    base.update(overrides)
    return OutboundEnvelope(**base)


class _Resp:
    def __init__(self, status_code, body=None, content=b""):
        self.status_code = status_code
        self._body = body if body is not None else {}
        self.text = str(self._body)
        self.content = content

    def json(self):
        return self._body


class _FakeGraph:
    """
    Serves every call the draft/reply paths make. Each createReply/
    createReplyAll/POST-/messages call mints a DISTINCT real
    internetMessageId, so a test can prove each result carries its own
    message's id rather than "the newest one in the conversation".
    """

    def __init__(self):
        self.calls: list[dict] = []
        self._n = 0
        self.conversation_id = "conv-shared"

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    def _mint(self, prefix):
        self._n += 1
        return {
            "id": f"draft-{self._n}",
            "conversationId": self.conversation_id,
            "internetMessageId": f"<{prefix}-{self._n}@mail.example.com>",
        }

    async def post(self, url, headers=None, json=None):
        self.calls.append({"method": "POST", "url": url, "json": json})
        if url.endswith("/send"):
            return _Resp(202)
        if url.endswith("/createReply") or url.endswith("/createReplyAll"):
            return _Resp(201, self._mint("reply"))
        if url.endswith("/reply") or url.endswith("/replyAll"):
            return _Resp(202)
        if url.endswith("/messages"):
            return _Resp(201, self._mint("new"))
        raise AssertionError(f"unexpected POST {url}")

    async def patch(self, url, headers=None, json=None):
        self.calls.append({"method": "PATCH", "url": url, "json": json})
        return _Resp(200, {"id": "patched"})

    async def get(self, url, headers=None):
        self.calls.append({"method": "GET", "url": url})
        if "/mailFolders/sentitems/messages" in url and "conversationId" in url:
            return _Resp(200, {"value": [{"id": "sent-item-id"}]})
        raise AssertionError(f"unexpected GET {url}")

    def posts(self, suffix):
        return [c for c in self.calls if c["method"] == "POST" and c["url"].endswith(suffix)]

    def patches(self):
        return [c for c in self.calls if c["method"] == "PATCH"]


async def _headers():
    return {"Authorization": "Bearer test-token"}


def _provider(monkeypatch) -> tuple[GraphMailProviderClient, _FakeGraph]:
    fake = _FakeGraph()
    monkeypatch.setattr(
        graph_client_module.httpx, "AsyncClient", lambda timeout=30.0, **_: fake
    )
    client = GraphMailProviderClient(
        auth_client=None,
        mailbox_address="mailbox@example.com",
        api_base_url="https://graph.microsoft.com/v1.0",
    )
    monkeypatch.setattr(client, "_authorized_headers", lambda: _headers())
    return client, fake


# ---------------------------------------------------------------
# Compose (new message) — draft path
# ---------------------------------------------------------------


async def test_compose_with_receipt_sets_graph_flag_and_captures_real_id(monkeypatch):
    client, fake = _provider(monkeypatch)

    result = await client.send_email(_envelope(read_receipt_requested=True))

    create = fake.posts("/messages")
    assert len(create) == 1
    assert create[0]["json"]["isReadReceiptRequested"] is True
    # Never a hand-built header — Graph hard-rejects non-x- headers.
    assert "internetMessageHeaders" not in create[0]["json"]
    assert len(fake.posts("/send")) == 1
    assert result.status == "SENT"
    # The id minted by the create response, available before sending.
    assert result.internet_message_id == "<new-1@mail.example.com>"


async def test_compose_without_receipt_has_no_flag_and_unchanged_message(monkeypatch):
    client, fake = _provider(monkeypatch)
    envelope = _envelope()

    await client.send_email(envelope)

    sent_body = fake.posts("/messages")[0]["json"]
    assert "isReadReceiptRequested" not in sent_body
    expected = _build_send_mail_message(envelope)
    expected.pop("attachments", None)
    assert sent_body == expected


def test_send_mail_message_builder_only_adds_flag_when_requested():
    assert "isReadReceiptRequested" not in _build_send_mail_message(_envelope())
    flagged = _build_send_mail_message(_envelope(read_receipt_requested=True))
    assert flagged["isReadReceiptRequested"] is True
    assert "internetMessageHeaders" not in flagged


# ---------------------------------------------------------------
# Reply / replyAll — createReply(All) + PATCH + send when requested
# ---------------------------------------------------------------


@pytest.mark.parametrize(
    "reply_all, create_suffix, direct_suffix",
    [(False, "/createReply", "/reply"), (True, "/createReplyAll", "/replyAll")],
)
async def test_requested_reply_uses_create_patch_send_never_direct_action(
    monkeypatch, reply_all, create_suffix, direct_suffix
):
    client, fake = _provider(monkeypatch)
    envelope = _envelope(
        read_receipt_requested=True,
        reply_to_provider_message_id="AAMk-original",
        reply_all=reply_all,
    )

    result = await client.send_email(envelope)

    # Never the direct action (it returns 202 with no usable id).
    assert fake.posts(direct_suffix) == []
    created = fake.posts(create_suffix)
    assert len(created) == 1
    # The flag is NOT in the createReply body (kept unchanged).
    assert created[0]["json"] == {"comment": "Hello there."}
    # ...it goes on the draft's PATCH, alongside the explicit recipients.
    patches = fake.patches()
    assert len(patches) == 1
    assert patches[0]["json"]["isReadReceiptRequested"] is True
    assert "internetMessageHeaders" not in patches[0]["json"]
    assert patches[0]["json"]["toRecipients"] == [
        {"emailAddress": {"address": "patient@example.com"}}
    ]
    assert len(fake.posts("/send")) == 1
    # Order: create -> patch -> send.
    methods = [(c["method"], c["url"].rsplit("/", 1)[-1]) for c in fake.calls[:3]]
    assert methods[0][1] in ("createReply", "createReplyAll")
    assert methods[1][0] == "PATCH"
    assert methods[2] == ("POST", "send")
    assert result.internet_message_id == "<reply-1@mail.example.com>"


@pytest.mark.parametrize(
    "reply_all, direct_suffix",
    [(False, "/reply"), (True, "/replyAll")],
)
async def test_ordinary_reply_keeps_the_existing_direct_route(
    monkeypatch, reply_all, direct_suffix
):
    client, fake = _provider(monkeypatch)
    envelope = _envelope(
        reply_to_provider_message_id="AAMk-original", reply_all=reply_all
    )

    result = await client.send_email(envelope)

    direct = fake.posts(direct_suffix)
    assert len(direct) == 1
    assert direct[0]["json"] == _build_reply_action_body(envelope)
    assert "isReadReceiptRequested" not in direct[0]["json"]["message"]
    assert fake.posts("/createReply") == [] and fake.posts("/createReplyAll") == []
    assert fake.patches() == []
    # The direct action returns no id: nothing is inferred.
    assert result.internet_message_id is None
    assert result.provider_message_id is None


async def test_unflagged_reply_draft_patch_has_no_flag(monkeypatch):
    # A reply that must use the draft path anyway (not receipt related)
    # must not gain the flag. Force it with an attachment-free reply
    # whose route is the draft path via no reply target.
    client, fake = _provider(monkeypatch)

    await client.send_email(_envelope(reply_to_provider_message_id=None))

    assert all("isReadReceiptRequested" not in c["json"] for c in fake.posts("/messages"))


async def test_rapid_replies_each_capture_their_own_real_id(monkeypatch):
    # Two flagged replies in the same conversation, back to back: ids
    # come from each create response, not from "newest sent item".
    client, fake = _provider(monkeypatch)
    first = await client.send_email(
        _envelope(read_receipt_requested=True, reply_to_provider_message_id="AAMk-1")
    )
    second = await client.send_email(
        _envelope(read_receipt_requested=True, reply_to_provider_message_id="AAMk-1")
    )

    assert first.internet_message_id == "<reply-1@mail.example.com>"
    assert second.internet_message_id == "<reply-2@mail.example.com>"
    assert first.internet_message_id != second.internet_message_id


async def test_internet_message_id_is_never_looked_up_after_sending(monkeypatch):
    client, fake = _provider(monkeypatch)

    await client.send_email(
        _envelope(read_receipt_requested=True, reply_to_provider_message_id="AAMk-1")
    )

    # The only GET is the pre-existing provider_message_id resolution
    # (Sent Items by conversationId); nothing asks for internetMessageId.
    gets = [c for c in fake.calls if c["method"] == "GET"]
    assert all("internetMessageId" not in c["url"] for c in gets)


async def test_failed_send_never_returns_a_result_with_an_id(monkeypatch):
    client, fake = _provider(monkeypatch)

    original_post = fake.post

    async def _post(url, headers=None, json=None):
        if url.endswith("/send"):
            fake.calls.append({"method": "POST", "url": url, "json": json})
            return _Resp(500, {"error": "boom"})
        return await original_post(url, headers=headers, json=json)

    monkeypatch.setattr(fake, "post", _post)

    with pytest.raises(GraphAPIError):
        await client.send_email(_envelope(read_receipt_requested=True))


# ---------------------------------------------------------------
# Envelope / provider contract
# ---------------------------------------------------------------


def test_envelope_flag_defaults_off_and_survives_persistence_round_trip():
    assert _envelope().read_receipt_requested is False
    flagged = _envelope(read_receipt_requested=True)
    # Retry Send replays the persisted envelope: the flag must survive.
    restored = OutboundEnvelope.model_validate(flagged.model_dump())
    assert restored.read_receipt_requested is True


async def test_mock_provider_honours_the_same_contract():
    result = await MockMailProviderClient().send_email(
        _envelope(read_receipt_requested=True)
    )
    assert result.status == "SENT"
    assert result.internet_message_id and result.internet_message_id.startswith("<mock-")
    assert await MockMailProviderClient().fetch_message_mime("anything") is None


def test_provider_interface_exposes_fetch_message_mime_with_a_safe_default():
    assert hasattr(MailProviderClient, "fetch_message_mime")


# ---------------------------------------------------------------
# Inbound fetch sites ask Graph for the item class
# ---------------------------------------------------------------


class _RecordingAuth:
    async def get_token(self, force_refresh: bool = False) -> str:
        return "t"


def _inbound_client(monkeypatch, response_factory):
    seen: list[str] = []

    class _Http:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def get(self, url, headers=None):
            seen.append(url)
            return response_factory(url)

    monkeypatch.setattr(
        graph_client_module.httpx, "AsyncClient", lambda timeout=30.0, **_: _Http()
    )
    client = GraphMailProviderClient(
        auth_client=_RecordingAuth(),
        mailbox_address="mailbox@example.com",
        api_base_url="https://graph.microsoft.com/v1.0",
    )
    return client, seen


def _graph_message(item_class=None) -> dict:
    item = {
        "id": "graph-id-1",
        "internetMessageId": "<receipt-1@example.com>",
        "subject": "Read: Hello",
        "from": {"emailAddress": {"address": "recipient@example.com"}},
        "toRecipients": [{"emailAddress": {"address": "inbox@example.com"}}],
        "body": {"contentType": "html", "content": "<p>was read</p>"},
        "internetMessageHeaders": [
            {"name": "Content-Type", "value": "application/ms-tnef"}
        ],
    }
    if item_class:
        # Graph echoes the requested id normalized (observed live).
        item["singleValueExtendedProperties"] = [
            {"id": "String 0x1a", "value": item_class}
        ]
    return item


async def test_fetch_message_requests_item_class_and_surfaces_it(monkeypatch):
    client, seen = _inbound_client(
        monkeypatch,
        lambda url: _Resp(200, _graph_message("REPORT.IPM.Note.IPNRN")),
    )

    payload = await client.fetch_message("graph-id-1")

    assert f"$expand={MESSAGE_ITEM_CLASS_EXPAND}" in seen[0]
    assert "String 0x001A" in seen[0]
    assert payload.item_class == "REPORT.IPM.Note.IPNRN"


async def test_list_new_messages_requests_item_class_and_surfaces_it(monkeypatch):
    client, seen = _inbound_client(
        monkeypatch,
        lambda url: _Resp(
            200,
            {"value": [_graph_message("REPORT.IPM.Note.IPNRN"), _graph_message("IPM.Note")]},
        ),
    )

    messages = await client.list_new_messages(since=datetime.now(timezone.utc))

    assert f"$expand={MESSAGE_ITEM_CLASS_EXPAND}" in seen[0]
    assert [m.item_class for m in messages] == ["REPORT.IPM.Note.IPNRN", "IPM.Note"]


async def test_item_class_is_none_when_graph_returns_no_extended_properties(monkeypatch):
    client, _ = _inbound_client(monkeypatch, lambda url: _Resp(200, _graph_message()))

    assert (await client.fetch_message("graph-id-1")).item_class is None


async def test_fetch_message_mime_returns_raw_bytes_and_raises_on_error(monkeypatch):
    mime = b"Content-Type: multipart/report\r\n\r\n"
    client, seen = _inbound_client(
        monkeypatch, lambda url: _Resp(200, content=mime)
    )
    assert await client.fetch_message_mime("graph-id-1") == mime
    assert seen[0].endswith("/messages/graph-id-1/$value")

    failing, _ = _inbound_client(monkeypatch, lambda url: _Resp(404, {"error": "x"}))
    with pytest.raises(GraphAPIError):
        await failing.fetch_message_mime("graph-id-1")
