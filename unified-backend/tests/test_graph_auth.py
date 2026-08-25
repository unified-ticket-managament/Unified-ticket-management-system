# test_graph_auth.py
#
# Pure-logic coverage for GraphAuthClient's 401-triggered force-refresh
# lever — no DB, no real network/Azure call. msal.ConfidentialClient
# Application is stubbed the same way test_graph_mail_integration.py
# already does (its own __init__ performs a real tenant-discovery
# HTTP call otherwise).

from app.ticketing.services.graph_auth import GRAPH_DEFAULT_SCOPE, GraphAuthClient


class _FakeTokenCache:
    """Minimal stand-in for msal.TokenCache — only the two methods
    GraphAuthClient._evict_cached_access_token actually calls."""

    class CredentialType:
        ACCESS_TOKEN = "access_token"

    def __init__(self, entries):
        self._entries = entries
        self.removed = []

    def search(self, credential_type, target=None):
        assert credential_type == self.CredentialType.ACCESS_TOKEN
        assert target == [GRAPH_DEFAULT_SCOPE]
        return list(self._entries)

    def remove_at(self, entry):
        self.removed.append(entry)
        self._entries.remove(entry)


class _FakeMsalApp:
    def __init__(self, entries):
        self.token_cache = _FakeTokenCache(entries)
        self.acquire_token_for_client_calls = 0

    def acquire_token_for_client(self, scopes):
        self.acquire_token_for_client_calls += 1
        return {"access_token": f"token-{self.acquire_token_for_client_calls}"}


def _build_client(monkeypatch, fake_app: _FakeMsalApp) -> GraphAuthClient:
    monkeypatch.setattr(
        "app.ticketing.services.graph_auth.msal.ConfidentialClientApplication",
        lambda **kwargs: fake_app,
    )
    monkeypatch.setattr("app.ticketing.services.graph_auth.msal.TokenCache", _FakeTokenCache)
    return GraphAuthClient(
        tenant_id="tenant-id", client_id="client-id", client_secret="client-secret"
    )


async def test_get_token_without_force_refresh_never_touches_the_cache(monkeypatch):
    fake_app = _FakeMsalApp(entries=["cached-entry"])
    client = _build_client(monkeypatch, fake_app)

    token = await client.get_token()

    assert token == "token-1"
    assert fake_app.token_cache.removed == []
    assert fake_app.token_cache._entries == ["cached-entry"]


async def test_get_token_with_force_refresh_evicts_the_cached_access_token(monkeypatch):
    fake_app = _FakeMsalApp(entries=["cached-entry"])
    client = _build_client(monkeypatch, fake_app)

    token = await client.get_token(force_refresh=True)

    assert token == "token-1"
    assert fake_app.token_cache.removed == ["cached-entry"]
    assert fake_app.token_cache._entries == []


async def test_get_token_with_force_refresh_is_a_no_op_when_cache_is_already_empty(
    monkeypatch,
):
    fake_app = _FakeMsalApp(entries=[])
    client = _build_client(monkeypatch, fake_app)

    token = await client.get_token(force_refresh=True)

    assert token == "token-1"
    assert fake_app.token_cache.removed == []
