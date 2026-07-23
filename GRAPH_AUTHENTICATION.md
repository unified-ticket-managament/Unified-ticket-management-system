# Graph Authentication — `graph_client.py` Review

## Finding: this file does not exist

A full repo search (filename glob for `**/graph_client.py`, plus a case-insensitive content grep for `graph_client` across the entire tree) returned **zero matches** for an actual source file. The only string hits anywhere in the repo are the proposed environment variable names `graph_client_id` / `graph_client_secret` in `EMAIL_ENVIRONMENT_GUIDE.md` (a doc this same review process wrote) — not a reference to a real file.

This is consistent with every prior report in this series:

- `EMAIL_INTEGRATION_ANALYSIS.md` — found no MSAL, no Azure AD app registration, no `ConfidentialClientApplication`, no `graph.microsoft.com` call anywhere in the codebase.
- `EMAIL_INTEGRATION_CHECKLIST.md` — lists a `GraphMailProviderClient` and MSAL client-credentials auth under "Missing items," not "Completed."
- `EMAIL_API_DOCUMENTATION.md` — confirmed none of the four real email endpoints perform any Graph-specific authentication.

So there is nothing to "review completely" for Client Credentials flow, token caching, token refresh, error handling, scopes, or authentication URLs — none of that code has been written yet. Below is what exists instead, and where the missing piece would slot in.

## What exists today (not authentication, but the seam it would plug into)

`unified-backend/app/ticketing/services/mail_provider.py` is the entire "Graph-adjacent" surface in this codebase:

```python
class MailProviderClient(ABC):
    @abstractmethod
    async def send_email(self, envelope: OutboundEnvelope) -> MailProviderSendResult:
        raise NotImplementedError


class MockMailProviderClient(MailProviderClient):
    async def send_email(self, envelope: OutboundEnvelope) -> MailProviderSendResult:
        ...  # logs only, fabricates a fake "SENT" result — no network call, no auth

def get_mail_provider_client() -> MailProviderClient:
    return MockMailProviderClient()  # the one line a future GraphMailProviderClient would replace
```

The file's own comments name the intended target directly: a future `GraphMailProviderClient`, calling `POST /users/{mailbox}/sendMail`, "authenticated through MSAL client-credentials flow once an Azure AD app registration and tenant credentials exist" — and explicitly instruct **"Do NOT implement that authentication yet."** That instruction has been followed; nothing beyond this comment exists.

## Point-by-point status against what was asked to verify

| Item requested | Status |
|---|---|
| Client Credentials flow | Not implemented. No `ConfidentialClientApplication`, no `msal`/`azure-identity` dependency in `requirements.txt`, no token-acquisition call anywhere. |
| Token caching | Not implemented. Nothing exists to cache an app-only access token, since none is ever acquired. |
| Token refresh | Not implemented. No refresh logic, since there's no initial token flow to refresh. |
| Error handling | Not implemented for Graph specifically. `MockMailProviderClient.send_email` cannot fail (it always returns `status="SENT"`), so no auth-failure, throttling (429), or transient-5xx handling has been designed. |
| Microsoft Graph scopes | Not configured anywhere. No `.default` scope request, no `Mail.Send`/`Mail.Read` permission reference in code (only mentioned prospectively in `EMAIL_INTEGRATION_CHECKLIST.md`'s Azure-dependencies section as permissions that will need to be granted). |
| Authentication URLs | Not present. No Azure AD authority URL (`https://login.microsoftonline.com/{tenant}`), no Graph API base URL (`https://graph.microsoft.com/v1.0`) appears anywhere in the codebase. |

## Where this would need to live, if built

Per the existing comments and this repo's own conventions:

- A new module — plausibly named `graph_client.py`, sitting alongside `mail_provider.py` in `unified-backend/app/ticketing/services/` — implementing `GraphMailProviderClient(MailProviderClient)`.
- New `Settings` fields in `unified-backend/app/core/config.py` for tenant ID, client ID, client secret, and mailbox address (none exist today — see `EMAIL_ENVIRONMENT_GUIDE.md`).
- `get_mail_provider_client()` in `mail_provider.py` updated to return the real client instead of the mock — the single swap point the code was deliberately designed around.

None of this exists yet. If you'd like, I can instead produce a forward-looking design/spec document proposing exactly how Client Credentials flow, token caching/refresh, error handling, scopes, and auth URLs *should* be structured in a future `graph_client.py` — clearly labeled as a proposal rather than a review of existing code. Let me know if that would be useful.
