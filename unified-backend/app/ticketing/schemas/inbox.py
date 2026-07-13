from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from app.ticketing.enums import InteractionDirection, InteractionStatus, TicketPriority


class InboxItemResponse(BaseModel):
    """
    Represents one email shown in the Account Manager inbox.

    Only summary information is returned. The full email content
    (and its replies) is retrieved using the thread-detail endpoint.
    """

    interaction_id: UUID

    client_id: UUID | None

    client_name: str

    from_email: str | None

    to_email: str | None

    subject: str

    message_id: str | None

    received_at: datetime

    status: InteractionStatus

    direction: InteractionDirection

    # Set when this root email was promoted to (or attached onto) a
    # ticket — populated in the "ticketed" and "all" views so those
    # rows can link straight to the ticket.
    ticket_id: UUID | None = None

    # Only meaningful once ticket_id is set — a pre-ticket Interaction
    # has neither (priority/category are chosen at ticket-creation
    # time), same convention as OpenEmailResponse's matching fields.
    ticket_priority: TicketPriority | None = None

    ticket_category: str | None = None

    has_attachments: bool = False

    # Set once someone claims this item via "Assign to me" — None
    # means unclaimed. Useful in the "all inboxes" supervisor view to
    # see who on the team has already picked something up.
    claimed_by: UUID | None = None
    claimed_by_name: str | None = None

    tags: list[str] = []

    folder_id: UUID | None = None

    # Outlook-style thread summary — how many replies (agent or
    # client) are filed under this root, and a snippet of the most
    # recent one, so the inbox row updates without opening the
    # thread. reply_count == 0 / latest_* == None means nobody has
    # replied yet — the row still shows the root email's own info.
    reply_count: int = 0

    latest_message: str | None = None

    latest_sender: str | None = None

    latest_at: datetime | None = None

    # Persisted read state (message_read_receipts), batched per page —
    # additive, defaults False so any consumer that doesn't know about
    # it yet is unaffected. Not currently wired into the frontend's own
    # rendering (which still uses its existing session-local `openedIds`
    # state) — this is the backend capability existing independently,
    # available for the frontend to adopt later without another schema
    # change.
    is_read: bool = False


class InboxResponse(BaseModel):
    """
    Account Manager Inbox Response.
    """

    total: int

    items: list[InboxItemResponse]

    # Opaque keyset-pagination cursor — set only when `limit` was
    # passed and the page came back full (implying more may exist).
    # Additive/optional so existing callers that don't know about it
    # are unaffected; pass it back as the `cursor` query param instead
    # of `offset` to page without OFFSET's cost-grows-with-depth
    # behavior. See InteractionRepository.list_inbox's docstring.
    next_cursor: str | None = None


class SentItemResponse(BaseModel):
    """
    One reply the current user has sent — pre-ticket or ticket-level
    alike. `client_name`/`subject` are borrowed from the reply's
    thread root (a bare REPLY interaction carries neither itself).
    """

    interaction_id: UUID

    root_interaction_id: UUID | None

    ticket_id: UUID | None

    client_id: UUID | None

    client_name: str

    subject: str

    message: str

    sent_at: datetime


class SentResponse(BaseModel):
    total: int

    items: list[SentItemResponse]


class DraftItemResponse(BaseModel):
    """
    One saved-but-unsent draft, listed alongside its thread's
    `client_name`/`subject` (borrowed from the thread root, same
    reasoning as `SentItemResponse`).
    """

    interaction_id: UUID

    root_interaction_id: UUID | None

    client_id: UUID | None

    client_name: str

    subject: str

    message: str

    created_at: datetime


class DraftListResponse(BaseModel):
    total: int

    items: list[DraftItemResponse]
