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


def _merge_cc(account_manager_email: str | None, extra_cc: list[str] | None) -> list[str]:
    """
    Combines the auto-added Account Manager Cc with whatever the
    agent typed into the reply/compose form's own Cc field, de-duped
    and order-preserving (agent-entered addresses first, since
    they're the ones the agent deliberately chose to add).
    """

    cc: list[str] = list(extra_cc or [])
    if account_manager_email and account_manager_email not in cc:
        cc.append(account_manager_email)
    return cc


def build_reply_envelope(
    client: Client,
    inbound_payload: EmailPayload,
    inbound_message_id: str | None,
    body: str,
    agent_name: str | None = None,
    account_manager_email: str | None = None,
    cc: list[str] | None = None,
    bcc: list[str] | None = None,
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
    without checking the platform. `cc`/`bcc` are whatever the agent
    themselves entered on the reply form, merged in alongside it.

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
        cc=_merge_cc(account_manager_email, cc),
        bcc=list(bcc or []),
        subject=_reply_subject(inbound_payload.subject),
        message_id=_new_message_id(client.inbox_email),
        in_reply_to=inbound_message_id,
        references=references,
        body=body,
    )


def build_compose_envelope(
    client: Client,
    to_email: str,
    subject: str,
    body: str,
    cc: list[str] | None = None,
    bcc: list[str] | None = None,
    agent_name: str | None = None,
    account_manager_email: str | None = None,
) -> OutboundEnvelope:
    """
    Builds the outbound envelope for a brand-new Compose message —
    the one Mail action with no prior inbound email to thread under,
    so unlike build_reply_envelope there's no inbound_payload to
    derive To/Subject/References from and no "nothing to dispatch"
    case (the agent always supplies a real To address via the form).
    Same From-is-always-the-shared-inbox rule as replies.
    """

    return OutboundEnvelope(
        from_email=client.inbox_email,
        from_name=agent_name,
        to_email=to_email,
        cc=_merge_cc(account_manager_email, cc),
        bcc=list(bcc or []),
        subject=subject,
        message_id=_new_message_id(client.inbox_email),
        in_reply_to=None,
        references=[],
        body=body,
    )
