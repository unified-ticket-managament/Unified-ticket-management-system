# graph_retry.py
#
# Shared retry/backoff wrapper for every Microsoft Graph HTTP call
# (graph_client.py, graph_subscription_service.py). Two policies,
# selected per call site via the retry_5xx/retry_on_transport_error
# kwargs:
#
# - SAFE (the default — every fetch/list, draft create/PATCH,
#   attachment add, upload-session create, and each upload-session
#   chunk PUT): retries 429 (respecting Retry-After), 5xx, and
#   transport errors (timeout/connect/read/protocol) — none of these
#   can produce a customer-visible duplicate on retry.
# - SEND (retry_5xx=False, retry_on_transport_error=False — the three
#   true send actions: sendMail, reply/replyAll, draft send): these
#   return 202 with no body, so a 5xx or a transport failure leaves
#   genuine ambiguity about whether Graph already accepted/is
#   processing the send — retrying either risks a duplicate customer
#   email. Only a 429 (a definitive synchronous rejection — nothing
#   was accepted) is safe to retry here.
#
# In both policies, any other 4xx is never retried, and a 401 always
# triggers exactly one forced token refresh + one retry (a second
# consecutive 401 is a real auth failure, not a stale-token problem,
# and is never retried again).

import asyncio
import logging
import random
from collections.abc import Awaitable, Callable

import httpx

logger = logging.getLogger(__name__)

RETRYABLE_5XX = frozenset({500, 502, 503, 504})
TRANSPORT_ERRORS = (
    httpx.TimeoutException,
    httpx.ConnectError,
    httpx.ReadError,
    httpx.RemoteProtocolError,
)

_BASE_DELAY_SECONDS = 1.0
_MAX_DELAY_SECONDS = 20.0


def _backoff_delay(attempt_index: int) -> float:
    """Exponential backoff (1s, 2s, 4s, ...) capped at
    _MAX_DELAY_SECONDS, with a small jitter so concurrent retries
    from multiple in-flight requests don't all wake up at once."""

    delay = min(_BASE_DELAY_SECONDS * (2**attempt_index), _MAX_DELAY_SECONDS)
    return delay + random.uniform(0, delay * 0.1)


def _retry_after_delay(response: httpx.Response) -> float | None:
    raw = response.headers.get("Retry-After")
    if raw is None:
        return None
    try:
        return max(0.0, float(raw))
    except ValueError:
        return None


async def call_with_graph_retry(
    attempt: Callable[[], Awaitable[httpx.Response]],
    *,
    operation: str,
    force_refresh_token: Callable[[], Awaitable[None]],
    retry_5xx: bool = True,
    retry_on_transport_error: bool = True,
    max_attempts: int = 4,
) -> httpx.Response:
    """
    Calls `attempt()` (one httpx request), retrying per the module
    docstring's rules. Returns the last httpx.Response as-is —
    including a still-bad one after retries are exhausted — so every
    existing call site's own `if response.status_code not in (...):
    raise GraphAPIError(...)` stays completely untouched: same
    exception type, same message, same downstream contract. A
    transport exception that isn't retried (or that survives every
    retry attempt) is re-raised, never swallowed.
    """

    already_refreshed_token = False
    attempt_index = 0

    while True:
        try:
            response = await attempt()
        except TRANSPORT_ERRORS:
            if retry_on_transport_error and attempt_index < max_attempts - 1:
                delay = _backoff_delay(attempt_index)
                logger.warning(
                    "Graph %s: transport error, retrying in %.1fs (attempt %d/%d)",
                    operation,
                    delay,
                    attempt_index + 1,
                    max_attempts,
                )
                await asyncio.sleep(delay)
                attempt_index += 1
                continue
            raise

        if response.status_code == 401 and not already_refreshed_token:
            logger.warning(
                "Graph %s: 401, forcing token refresh and retrying once", operation
            )
            already_refreshed_token = True
            await force_refresh_token()
            continue

        if response.status_code == 429 and attempt_index < max_attempts - 1:
            delay = _retry_after_delay(response)
            if delay is None:
                delay = _backoff_delay(attempt_index)
            logger.warning(
                "Graph %s: 429, retrying in %.1fs (attempt %d/%d)",
                operation,
                delay,
                attempt_index + 1,
                max_attempts,
            )
            await asyncio.sleep(delay)
            attempt_index += 1
            continue

        if (
            retry_5xx
            and response.status_code in RETRYABLE_5XX
            and attempt_index < max_attempts - 1
        ):
            delay = _backoff_delay(attempt_index)
            logger.warning(
                "Graph %s: %d, retrying in %.1fs (attempt %d/%d)",
                operation,
                response.status_code,
                delay,
                attempt_index + 1,
                max_attempts,
            )
            await asyncio.sleep(delay)
            attempt_index += 1
            continue

        return response
