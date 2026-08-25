from pydantic import BaseModel, EmailStr, Field


class EnvelopeAttachment(BaseModel):
    """
    One file ready to ride along on an outbound send. See
    attachment_service.load_envelope_attachments, the one place this
    is built, for exactly how — either shape below can be produced,
    depending on size:

    - Small (<= attachment_service.GRAPH_INLINE_ATTACHMENT_MAX_BYTES):
      content already read out of storage and base64-encoded
      (`content_base64` set, `storage_key`/`size_bytes` unset), so
      the mail transport (graph_client.py) can embed it directly in a
      single sendMail/reply call with no storage/DB access of its own.
    - Large (over that threshold, but always within Graph's own real
      ~150MB attachment ceiling, since UTMS's own
      MAX_ATTACHMENT_SIZE_BYTES caps every stored attachment well
      below that): `content_base64` is left unset and `storage_key`/
      `size_bytes` are set instead — this envelope is itself persisted
      verbatim into Interaction.payload, and a multi-megabyte base64
      blob has no business living in a JSONB column. graph_client.py
      fetches the real bytes fresh, once, at actual dispatch time via
      a genuine Graph upload session (see its _add_large_attachment).
    """

    filename: str
    content_type: str
    content_base64: str | None = None

    # Only set for a pasted-inline-image attachment (see
    # attachment_service.create_inline_image) — content_id is the
    # value referenced as `cid:{content_id}` inside the envelope's own
    # body_html, and is_inline tells graph_client.py to mark the
    # resulting Graph attachment dict isInline=True so it renders
    # embedded in the body instead of as a separate downloadable file.
    # None/False (the default) for every ordinary attachment — the
    # exact same 3-field shape as before this pair existed.
    content_id: str | None = None
    is_inline: bool = False

    # Large-attachment reference (see class docstring). Both unset
    # (the default) for every small attachment — the exact same shape
    # as before this pair existed.
    storage_key: str | None = None
    size_bytes: int | None = None


class OutboundEnvelope(BaseModel):
    """
    A fully-addressed outbound email, built by the platform before a
    reply leaves it. Stored inside the OUTBOUND interaction's
    payload (payload.envelope) — this is the seam Task 1's transport
    layer reads from to actually send the mail.

    from_email is always the client's dedicated shared inbox address
    (never an agent's personal address) — that's what keeps the
    client's next reply routable back through the platform.
    """

    from_email: EmailStr
    from_name: str | None = None

    to_email: EmailStr

    # Full multi-recipient "To" list for a genuinely multi-recipient
    # send (Manual Forward and Compose, both of which can resolve
    # multiple internal users/external emails/Distribution List
    # members into one send; build_reply_envelope sets this too, when
    # an agent picks more than one "To" override on a reply). None
    # (the default) means "send to to_email alone, exactly as before
    # this field existed" — Compose/Forward/Reply's own single-
    # recipient case all leave this unset and are completely
    # unaffected. When set, graph_client.py's _build_send_mail_message,
    # _build_reply_action_body, and _create_reply_draft all use this
    # in place of [to_email] for Graph's toRecipients — Microsoft
    # Graph's sendMail/reply/replyAll actions already natively support
    # multiple toRecipients in one call.
    to_emails: list[EmailStr] | None = None

    # The client's Account Manager, auto-added so they see every
    # reply in their real inbox without checking the platform, plus
    # whatever the agent themselves added via the reply/compose form.
    cc: list[EmailStr] = Field(default_factory=list)

    bcc: list[EmailStr] = Field(default_factory=list)

    subject: str

    # Newly generated for this reply, stored on the interaction so a
    # future inbound reply's In-Reply-To can be matched back to it.
    message_id: str

    in_reply_to: str | None = None
    references: list[str] = Field(default_factory=list)

    body: str

    # Optional sanitized HTML counterpart to `body` (Outlook-style
    # clipboard paste — pasted rich text/tables/inline images) — see
    # email_envelope.py, the one place this is populated (via
    # html_sanitizer.sanitize_outbound_html) and graph_client.py, the
    # one place that reads it. None (the default) means "send exactly
    # like every send before this field existed" — a plain-text-only
    # message, body.contentType="Text". `body` itself is still always
    # populated as the real plain-text fallback (e.g. for a mail
    # client that renders text/plain, or a future non-Graph provider).
    body_html: str | None = None

    attachments: list[EnvelopeAttachment] = Field(default_factory=list)

    # Microsoft Graph's own native message id of the inbound message
    # this envelope is replying to (EmailPayload.provider_message_id,
    # see that field's docstring) — None for a brand-new Compose (no
    # prior message to reply to) or when the message being replied to
    # arrived via a transport that never captured Graph's own id.
    # GraphMailProviderClient.send_email uses this to call Graph's
    # reply/replyAll action on the real message instead of sendMail,
    # keeping the send genuinely threaded in Outlook/Gmail; None here
    # means "send with sendMail", exactly as before this field existed.
    reply_to_provider_message_id: str | None = None

    # Only meaningful alongside reply_to_provider_message_id — selects
    # Graph's replyAll action instead of reply. Ignored (treated as
    # plain sendMail) when reply_to_provider_message_id is None.
    reply_all: bool = False
