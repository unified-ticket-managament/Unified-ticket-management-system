# test_graph_retry.py
#
# Pure-logic coverage for graph_retry.call_with_graph_retry — no DB,
# no real network call. Verifies both retry policies explicitly:
# the SAFE policy (retry_5xx=True, retry_on_transport_error=True,
# used by every fetch/list/draft/attachment/upload-session call) and
# the SEND policy (retry_5xx=False, retry_on_transport_error=False,
# used only by sendMail/reply/replyAll/draft-send — see graph_client.py)
# — a 5xx or transport error on an outbound send is genuinely
# ambiguous about whether Graph already accepted the send, so neither
# is retried there, while both are safe to retry everywhere else.

import httpx
import pytest

from app.ticketing.services.graph_retry import call_with_graph_retry


class _FakeResponse:
    def __init__(self, status_code: int, headers: dict | None = None):
        self.status_code = status_code
        self.headers = headers or {}


def _sequence_attempt(responses):
    """Returns an `attempt` callable that pops one entry off `responses`
    per call — either an httpx.Response-shaped object, or an exception
    instance to raise. Raises if called more times than there are
    entries (i.e. an unexpected extra retry)."""

    calls = {"count": 0}

    async def _attempt():
        calls["count"] += 1
        if not responses:
            raise AssertionError("call_with_graph_retry made more attempts than expected")
        item = responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    _attempt.calls = calls
    return _attempt


class _ForceRefreshTracker:
    def __init__(self):
        self.call_count = 0

    async def __call__(self):
        self.call_count += 1


def _mock_sleep(monkeypatch):
    """Replaces asyncio.sleep with an instant no-op that records the
    requested delay — keeps these tests fast without changing any
    retry/backoff decision logic under test."""

    sleeps: list[float] = []

    async def _fake_sleep(seconds):
        sleeps.append(seconds)

    monkeypatch.setattr("app.ticketing.services.graph_retry.asyncio.sleep", _fake_sleep)
    return sleeps


# ---------------------------------------------------------
# SAFE policy (the default) — 429/5xx/transport errors all retried
# ---------------------------------------------------------


async def test_safe_policy_retries_429_and_respects_retry_after(monkeypatch):
    sleeps = _mock_sleep(monkeypatch)

    attempt = _sequence_attempt(
        [_FakeResponse(429, headers={"Retry-After": "5"}), _FakeResponse(200)]
    )
    refresh = _ForceRefreshTracker()

    response = await call_with_graph_retry(attempt, operation="test", force_refresh_token=refresh)

    assert response.status_code == 200
    assert sleeps == [5.0]
    assert refresh.call_count == 0


async def test_safe_policy_retries_5xx_into_eventual_success(monkeypatch):
    _mock_sleep(monkeypatch)

    attempt = _sequence_attempt([_FakeResponse(503), _FakeResponse(500), _FakeResponse(200)])
    refresh = _ForceRefreshTracker()

    response = await call_with_graph_retry(attempt, operation="test", force_refresh_token=refresh)

    assert response.status_code == 200


async def test_safe_policy_retries_transport_error_into_eventual_success(monkeypatch):
    _mock_sleep(monkeypatch)

    attempt = _sequence_attempt([httpx.ConnectError("boom"), _FakeResponse(200)])
    refresh = _ForceRefreshTracker()

    response = await call_with_graph_retry(attempt, operation="test", force_refresh_token=refresh)

    assert response.status_code == 200


async def test_safe_policy_never_retries_other_4xx():
    attempt = _sequence_attempt([_FakeResponse(404)])
    refresh = _ForceRefreshTracker()

    response = await call_with_graph_retry(attempt, operation="test", force_refresh_token=refresh)

    assert response.status_code == 404
    assert attempt.calls["count"] == 1


async def test_safe_policy_exhausts_retries_and_returns_last_bad_response(monkeypatch):
    _mock_sleep(monkeypatch)

    # max_attempts=2 -> exactly one retry is allowed.
    attempt = _sequence_attempt([_FakeResponse(503), _FakeResponse(503)])
    refresh = _ForceRefreshTracker()

    response = await call_with_graph_retry(
        attempt, operation="test", force_refresh_token=refresh, max_attempts=2
    )

    assert response.status_code == 503
    assert attempt.calls["count"] == 2


async def test_safe_policy_reraises_transport_error_once_retries_exhausted(monkeypatch):
    _mock_sleep(monkeypatch)

    attempt = _sequence_attempt([httpx.TimeoutException("t1"), httpx.TimeoutException("t2")])
    refresh = _ForceRefreshTracker()

    with pytest.raises(httpx.TimeoutException):
        await call_with_graph_retry(
            attempt, operation="test", force_refresh_token=refresh, max_attempts=2
        )


# ---------------------------------------------------------
# 401 handling — identical under both policies
# ---------------------------------------------------------


async def test_401_forces_refresh_and_retries_once_under_safe_policy():
    attempt = _sequence_attempt([_FakeResponse(401), _FakeResponse(200)])
    refresh = _ForceRefreshTracker()

    response = await call_with_graph_retry(attempt, operation="test", force_refresh_token=refresh)

    assert response.status_code == 200
    assert refresh.call_count == 1


async def test_second_consecutive_401_is_not_retried_again():
    attempt = _sequence_attempt([_FakeResponse(401), _FakeResponse(401)])
    refresh = _ForceRefreshTracker()

    response = await call_with_graph_retry(attempt, operation="test", force_refresh_token=refresh)

    assert response.status_code == 401
    assert refresh.call_count == 1
    assert attempt.calls["count"] == 2


async def test_401_forces_refresh_and_retries_once_under_send_policy():
    attempt = _sequence_attempt([_FakeResponse(401), _FakeResponse(202)])
    refresh = _ForceRefreshTracker()

    response = await call_with_graph_retry(
        attempt,
        operation="sendMail",
        force_refresh_token=refresh,
        retry_5xx=False,
        retry_on_transport_error=False,
    )

    assert response.status_code == 202
    assert refresh.call_count == 1


# ---------------------------------------------------------
# SEND policy — 429 retried, but 5xx/transport errors never retried
# (a 5xx or a transport failure is ambiguous about whether Graph
# already accepted the send — see graph_client.py's sendMail/
# _send_reply/_send_draft, the only three callers using this policy).
# ---------------------------------------------------------


async def test_send_policy_still_retries_429(monkeypatch):
    _mock_sleep(monkeypatch)

    attempt = _sequence_attempt([_FakeResponse(429), _FakeResponse(202)])
    refresh = _ForceRefreshTracker()

    response = await call_with_graph_retry(
        attempt,
        operation="sendMail",
        force_refresh_token=refresh,
        retry_5xx=False,
        retry_on_transport_error=False,
    )

    assert response.status_code == 202


async def test_send_policy_never_retries_5xx():
    # Only one response queued — a retry attempt would raise
    # AssertionError from _sequence_attempt, failing the test.
    attempt = _sequence_attempt([_FakeResponse(503)])
    refresh = _ForceRefreshTracker()

    response = await call_with_graph_retry(
        attempt,
        operation="sendMail",
        force_refresh_token=refresh,
        retry_5xx=False,
        retry_on_transport_error=False,
    )

    assert response.status_code == 503
    assert attempt.calls["count"] == 1


async def test_send_policy_never_retries_transport_error():
    attempt = _sequence_attempt([httpx.TimeoutException("boom")])
    refresh = _ForceRefreshTracker()

    with pytest.raises(httpx.TimeoutException):
        await call_with_graph_retry(
            attempt,
            operation="sendMail",
            force_refresh_token=refresh,
            retry_5xx=False,
            retry_on_transport_error=False,
        )

    assert attempt.calls["count"] == 1


async def test_send_policy_never_retries_other_4xx():
    attempt = _sequence_attempt([_FakeResponse(400)])
    refresh = _ForceRefreshTracker()

    response = await call_with_graph_retry(
        attempt,
        operation="sendMail",
        force_refresh_token=refresh,
        retry_5xx=False,
        retry_on_transport_error=False,
    )

    assert response.status_code == 400
    assert attempt.calls["count"] == 1
