# ADR-008: Microsoft Graph Integration With a Mock-Provider Fallback

**Status**: Accepted (implemented, in production use)

## Context

Client communication is primarily email-based, routed through an organization's own mailbox (Microsoft 365/Exchange, given the Graph API choice). Developers need to be able to work on ticket/mail features locally without real mailbox credentials.

## Problem

How should the system integrate with a real mailbox, while staying developable without one?

## Options Considered

1. **Require real Graph credentials for all local development** — highest fidelity, but blocks anyone without a test mailbox from working on mail-adjacent features at all.
2. **A factory that returns a real Graph client when configured, or a `MockMailProviderClient` when any of the four required settings (`GRAPH_TENANT_ID`/`GRAPH_CLIENT_ID`/`GRAPH_CLIENT_SECRET`/`GRAPH_MAILBOX_ADDRESS`) is missing** — `mail_provider.get_mail_provider_client()`.

## Decision

Option 2.

## Reason

This lets the entire ticket/mail feature set be developed and tested locally with zero external dependencies, while production/staging environments with real credentials get real mailbox behavior automatically — no code branching needed at call sites, since both providers implement the same interface.

## Trade-offs

- **Cost**: a genuine class of Graph-API-specific bugs (the `$select`/`contentBytes` OData incompatibility, the `odata_type` absence-when-not-selected quirk) can only be caught by testing against the real Graph API — the mock provider, by construction, can't reproduce provider-specific quirks it was never designed to have. All three of the "stacked attachment bugs" documented in [16-known-limitations/integration-limitations.md](../16-known-limitations/integration-limitations.md) were only found via live testing against a real mailbox, not via the mock provider or unit tests.
- **Cost**: two parallel inbound transports exist (webhook subscription + polling fallback) specifically because a webhook requires a publicly-reachable HTTPS URL that local development doesn't have — adding real operational complexity (subscription renewal scheduling, per-mailbox poll-state tracking) that a single-transport design wouldn't need.
- **Benefit**: onboarding a new developer requires zero Microsoft Entra ID setup to be productive on most of the codebase (see [13-developer-onboarding/prerequisites.md](../13-developer-onboarding/prerequisites.md)) — a real, confirmed reduction in setup friction.

## Consequences

Any change to the mail-intake pipeline should ideally be verified against the real Graph API before being considered production-proven — this codebase's own history explicitly flags several features as "confirmed via unit tests / mock provider, not yet live-verified against real Graph" as a distinct, weaker claim, reflecting an awareness that the mock provider cannot substitute for this verification.

## Related Components

`app/ticketing/services/{graph_client,graph_auth,mail_provider}.py`, `app/ticketing/services/graph_mail_poller.py`, `app/core/{graph_mail_poll_scheduler,graph_subscription_scheduler}.py`.
