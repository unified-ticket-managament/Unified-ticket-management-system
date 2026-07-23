# email_envelope.py

from uuid import uuid4

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
    from_email: str,
    inbound_payload: EmailPayload,
    inbound_message_id: str | None,
    body: str,
    agent_name: str | None = None,
    account_manager_email: str | None = None,
    cc: list[str] | None = None,
    bcc: list[str] | None = None,
    to_email_override: str | None = None,
) -> OutboundEnvelope | None:
    """
    Builds the outbound envelope for a reply: From is always the
    shared inbox the original message arrived at (never an agent's
    personal address — that's what keeps the client's next answer
    routable back through the platform), To is the original sender by
    default, and the subject/threading headers keep the conversation
    linked for the client's mail client and for our own inbound
    thread-matching.

    `from_email` is a plain address string, not a Client object — the
    caller always resolves it to the inbound message's own arrival
    address (EmailPayload.to_email), whether or not a Client matched
    (see email_service.py's is_configured_graph_mailbox()). Never
    `Client.inbox_email`, which now stores the client's own real
    address (the one they send FROM), not an address this platform
    can send from — replying FROM the same address the message
    arrived AT is correct in every case, this function doesn't need
    to know which one it's in.

    `agent_name` is display-only (From address stays the shared
    inbox). `account_manager_email`, when known, is auto-added to Cc
    so the Account Manager sees every reply in their real mailbox
    without checking the platform — None for a client-less thread,
    since there's no Account Manager to notify. `cc`/`bcc` are
    whatever the agent themselves entered on the reply form, merged in
    alongside it. `to_email_override`, when the agent picked a
    different contact from the "To" dropdown instead of the thread's
    own sender, wins over `inbound_payload.from_email` — still
    requires a resolvable recipient somewhere, so an override can't be
    used to bypass the "nothing to dispatch" case below.

    Returns None if there's no sender to reply to (e.g. a reply on a
    ticket whose originating email is unknown) — callers should treat
    that as "nothing to dispatch" rather than an error.
    """

    recipient = to_email_override or inbound_payload.from_email
    if not recipient:
        return None

    references = list(inbound_payload.references)
    if inbound_message_id:
        references.append(inbound_message_id)

    return OutboundEnvelope(
        from_email=from_email,
        from_name=agent_name,
        to_email=recipient,
        cc=_merge_cc(account_manager_email, cc),
        bcc=list(bcc or []),
        subject=_reply_subject(inbound_payload.subject),
        message_id=_new_message_id(from_email),
        in_reply_to=inbound_message_id,
        references=references,
        body=body,
    )


def build_compose_envelope(
    from_email: str,
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

    `from_email` is the shared support mailbox address (the caller
    resolves it, same convention as build_reply_envelope) — never
    `Client.inbox_email`, which now stores the client's own real
    address (the one they send FROM), not an address this platform
    can send from.
    """

    return OutboundEnvelope(
        from_email=from_email,
        from_name=agent_name,
        to_email=to_email,
        cc=_merge_cc(account_manager_email, cc),
        bcc=list(bcc or []),
        subject=subject,
        message_id=_new_message_id(from_email),
        in_reply_to=None,
        references=[],
        body=body,
    )
