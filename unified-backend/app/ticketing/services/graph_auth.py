# graph_auth.py
#
# MSAL client-credentials (app-only) token acquisition for Microsoft
# Graph — the one piece of Graph authentication this codebase has,
# used by GraphMailProviderClient (graph_client.py) for both sending
# and fetching mail. Never touches a signed-in user; this app acts
# entirely as itself against a shared mailbox, authorized via an Azure
# AD app registration (see AZURE_SETUP_GUIDE.md).

import asyncio
import logging
from functools import lru_cache

import msal

from app.core.config import Settings

logger = logging.getLogger(__name__)

GRAPH_DEFAULT_SCOPE = "https://graph.microsoft.com/.default"


class GraphAuthError(Exception):
    """Raised when Graph token acquisition itself fails (bad credentials,
    tenant misconfiguration, admin consent missing, etc.) — distinct
    from a Graph API call failing after a token was already obtained."""


class GraphAuthClient:
    """
    Thin wrapper around msal.ConfidentialClientApplication. Token
    caching and refresh are handled by MSAL itself: the same
    ConfidentialClientApplication instance keeps its own in-memory
    token cache, and acquire_token_for_client() transparently returns
    the cached token until it's near expiry, then silently reacquires
    — callers never need their own cache or expiry bookkeeping, only
    to keep reusing the same GraphAuthClient instance (see
    get_graph_auth_client()'s lru_cache below).
    """

    def __init__(self, tenant_id: str, client_id: str, client_secret: str):
        # msal.ConfidentialClientApplication.__init__ always performs a
        # real, synchronous "tenant discovery" HTTP call regardless of
        # validate_authority (that flag only skips *instance* discovery
        # — see msal's own Authority.__init__ docstring) — there is no
        # way to construct one against a placeholder/unreachable tenant
        # without a network call. _cached_graph_auth_client (below)
        # bounds this to at most once per process per configured
        # identity, not once per send/fetch call.
        self._app = msal.ConfidentialClientApplication(
            client_id=client_id,
            client_credential=client_secret,
            authority=f"https://login.microsoftonline.com/{tenant_id}",
        )

    async def get_token(self) -> str:
        # acquire_token_for_client is a blocking network call under the
        # hood (same reasoning as SMTPEmailSender's asyncio.to_thread
        # use in email_sender.py) — never block the event loop with it.
        result = await asyncio.to_thread(
            self._app.acquire_token_for_client, scopes=[GRAPH_DEFAULT_SCOPE]
        )

        if "access_token" not in result:
            logger.error(
                "Graph token acquisition failed: %s — %s",
                result.get("error"),
                result.get("error_description"),
            )
            raise GraphAuthError(
                result.get("error_description") or "Graph token acquisition failed."
            )

        return result["access_token"]


@lru_cache(maxsize=1)
def _cached_graph_auth_client(tenant_id: str, client_id: str, client_secret: str) -> GraphAuthClient:
    """
    Keyed on the credential values themselves (not the Settings object,
    which isn't hashable) so the *same* GraphAuthClient — and therefore
    the same underlying msal.ConfidentialClientApplication and its
    internal token cache — is reused across every call in the process.
    This is what actually makes token caching/reuse real: constructing
    a fresh ConfidentialClientApplication per call would mean a cold,
    empty token cache (and, before validate_authority=False above, a
    repeated discovery round trip) every single time. maxsize=1 is
    deliberate — one configured Graph identity per process is the only
    supported shape today.
    """

    return GraphAuthClient(
        tenant_id=tenant_id,
        client_id=client_id,
        client_secret=client_secret,
    )


def build_graph_auth_client(settings: Settings) -> GraphAuthClient | None:
    """
    Returns None whenever Graph identity settings aren't fully
    provisioned yet — the same "degrade to nothing configured" shape
    get_email_sender() already uses for smtp_host. Callers (chiefly
    get_mail_provider_client() in mail_provider.py) use this to decide
    between GraphMailProviderClient and MockMailProviderClient.
    """

    if not (settings.graph_tenant_id and settings.graph_client_id and settings.graph_client_secret):
        return None

    return _cached_graph_auth_client(
        settings.graph_tenant_id,
        settings.graph_client_id,
        settings.graph_client_secret,
    )
