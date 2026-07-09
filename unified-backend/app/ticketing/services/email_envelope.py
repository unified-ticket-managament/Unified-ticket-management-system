# email_envelope.py

from uuid import uuid4

from app.ticketing.models.client import Client
from app.ticketing.schemas.payloads import EmailPayload, OutboundEnvelope


def _reply_subject(original_subject: str) -> str:
    """
    Prefixes with "Re: " unless the subject is already a reply,
    so a long thread doesn't accumulate "Re: Re: Re: ...".
    """

    if original_subject.strip().lower().startswith("re:"):
        return original_subject
    return f"Re: {original_subject}"


def _new_message_id(from_email: str) -> str:
    domain = from_email.split("@", 1)[-1] or "probeps.com"
    return f"<{uuid4().hex}@{domain}>"


def build_reply_envelope(
    client: Client,
    inbound_payload: EmailPayload,
    inbound_message_id: str | None,
    body: str,
    agent_name: str | None = None,
    account_manager_email: str | None = None,
) -> OutboundEnvelope | None:
    """
    Builds the outbound envelope for a reply: From is always the
    client's shared inbox (never an agent's personal address — that's
    what keeps the client's next answer routable back through the
    platform), To is the original sender, and the subject/threading
    headers keep the conversation linked for the client's mail client
    and for our own inbound thread-matching.

    `agent_name` is display-only (From address stays the shared
    inbox). `account_manager_email`, when known, is auto-added to Cc
    so the Account Manager sees every reply in their real mailbox
    without checking the platform.

    Returns None if there's no sender to reply to (e.g. a reply on a
    ticket whose originating email is unknown) — callers should treat
    that as "nothing to dispatch" rather than an error.
    """

    if not inbound_payload.from_email:
        return None

    references = list(inbound_payload.references)
    if inbound_message_id:
        references.append(inbound_message_id)

    return OutboundEnvelope(
        from_email=client.inbox_email,
        from_name=agent_name,
        to_email=inbound_payload.from_email,
        cc=[account_manager_email] if account_manager_email else [],
        subject=_reply_subject(inbound_payload.subject),
        message_id=_new_message_id(client.inbox_email),
        in_reply_to=inbound_message_id,
        references=references,
        body=body,
    )
