# email_envelope.py

from uuid import uuid4

from shared_models.models import User

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


def build_agent_signature(current_user: User) -> str:
    """
    The one shared signature block appended to every human-composed
    outbound message (Compose/Forward via compose_email, Reply via
    add_reply/add_interaction_reply, and transitively Draft-Send via
    add_interaction_reply) — identifies the employee who wrote the
    message, never the mailbox it's sent from (that's resolved
    separately, per-message, and can vary between a Compose/Reply on
    the shared inbox vs. a client-specific one — see
    outbound_dispatcher.py). Baking a specific address in here would
    go stale the moment a client's mailbox differs from whatever was
    true when this function was last read.

    Every field beyond `name` is nullable on the User model (Profile
    module fields) and rendered only when actually set. `designation`
    (the real-world job title) is preferred over `role.name` (the
    RBAC role) when present, since it's the more accurate "what this
    person's title is" answer — falls back to role.name, then to
    nothing, exactly like the original single-caller version of this
    function already guarded for a possibly-None role.

    Note: on an RBAC-cache-hit request, the transient User
    reconstructed from JWT claims only carries name/role — designation/
    phone_number/department read back as None for the remainder of
    that cache TTL window even if the real row has them set (see
    app/dependencies/auth.py's _build_transient_user). An already-
    accepted staleness tradeoff, not a bug to work around here.
    """

    divider = "-" * 40

    title = current_user.designation or (
        current_user.role.name if current_user.role is not None else None
    )

    lines = [divider, "Regards,", current_user.name]
    if title:
        lines.append(title)
    lines.append("Probe Practice Solutions")
    if current_user.department:
        lines.append(current_user.department)
    if current_user.phone_number:
        lines.append(current_user.phone_number)
    lines.append(divider)

    return "\n".join(lines)


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
    reply_to_provider_message_id: str | None = None,
    reply_all: bool = False,
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

    `reply_to_provider_message_id`, when known (the inbound message's
    own Graph id — see EmailPayload.provider_message_id), makes the
    resulting envelope threaded via Graph's real reply/replyAll action
    instead of sendMail (see graph_client.py); `reply_all` selects
    which of the two. None/False (the default) preserves the old
    sendMail-only behavior exactly.

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
        reply_to_provider_message_id=reply_to_provider_message_id,
        reply_all=reply_all,
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
