from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import and_, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.ticketing.enums import InteractionDirection, InteractionStatus
from app.ticketing.models.client import Client
from app.ticketing.models.interaction import Interaction
from app.ticketing.models.ticket import Ticket
from app.ticketing.schemas.interaction import (
    InteractionCreate,
    InteractionUpdate,
)


class InteractionRepository:

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(
        self,
        data: InteractionCreate,
    ) -> Interaction:

        interaction = Interaction(**data.model_dump())

        self.db.add(interaction)

        await self.db.flush()

        await self.db.refresh(interaction)

        return interaction

    async def get_by_id(
        self,
        interaction_id: UUID,
    ) -> Interaction | None:

        result = await self.db.execute(

            select(Interaction).where(
                Interaction.interaction_id == interaction_id
            )

        )

        return result.scalar_one_or_none()

    async def list_by_ticket_id(
        self,
        ticket_id: UUID,
    ) -> list[Interaction]:

        result = await self.db.execute(

            select(Interaction)
            .where(
                Interaction.ticket_id == ticket_id
            )
            .order_by(
                Interaction.created_at.asc()
            )

        )

        return list(result.scalars().all())

    async def list_by_ticket_ids(
        self,
        ticket_ids: list[UUID],
    ) -> list[Interaction]:
        """
        Same shape as list_by_ticket_id, batched over many tickets at
        once — lets a page that needs every visible ticket's timeline
        (the Interactions page) run one query instead of one request
        per ticket.
        """

        if not ticket_ids:
            return []

        result = await self.db.execute(
            select(Interaction)
            .where(Interaction.ticket_id.in_(ticket_ids))
            .order_by(Interaction.created_at.asc())
        )

        return list(result.scalars().all())

    async def list_inbox(
        self,
        account_manager_id: UUID | None = None,
        client_id: UUID | None = None,
        view: str = "pending",
        folder_id: UUID | None = None,
        ticket_type: str | None = None,
        assigned_agent_id: UUID | None = None,
    ) -> list[Interaction]:
        """
        The role-scoped inbox query — always over thread ROOTS
        (parent_interaction_id IS NULL, interaction_type == "EMAIL");
        replies are fetched separately via `list_thread` once a root
        is opened.

        - `account_manager_id` set: only mail belonging to clients
          that AM owns (a join against `clients`). None (and
          `ticket_type`/`assigned_agent_id` also None) means "every
          client" — the Site Lead/Super Admin global inbox.
        - `client_id` set: further narrows to one client (the
          per-client filter on the inbox UI).
        - `folder_id` set: further narrows to one custom folder —
          orthogonal to `view` (a folder can hold items in any
          status), so this composes with any of the views below
          rather than being its own view.
        - `ticket_type` set: Team Lead scoping — only threads whose
          ticket is filed under this work-specialization category.
          Implemented as an INNER join against `tickets`, so this
          also implicitly restricts to ticketed threads only (a
          Team Lead never sees a still-pending, pre-ticket item —
          see the role propagation rules in InboxService.get_inbox).
        - `assigned_agent_id` set: Staff scoping — only threads whose
          ticket is currently assigned to (claimed by) this agent.
          Same inner-join-implies-ticketed-only reasoning as above.
        - `view`:
          - "pending": not yet replied to or ticketed, and not
            currently snoozed — the triage queue.
          - "replied": answered directly, never became a ticket.
          - "ticketed": promoted to (or attached onto) a ticket.
          - "archived": marked Informational/Archive — stored, no
            ticket, no work assignment, still searchable here.
          - "snoozed": pending, but hidden from "pending" until
            `snoozed_until` — resurfaces automatically, no background
            job needed since this is just a `now()` comparison on read.
          - "all": every root email regardless of state — the "All
            Inboxes" overview, normally paired with no account_manager
            scoping.
        """

        query = select(Interaction)

        if account_manager_id is not None or client_id is not None:
            query = query.join(Client, Client.client_id == Interaction.client_id)

        if account_manager_id is not None:
            query = query.where(Client.account_manager_id == account_manager_id)

        if client_id is not None:
            query = query.where(Interaction.client_id == client_id)

        if ticket_type is not None or assigned_agent_id is not None:
            query = query.join(Ticket, Ticket.ticket_id == Interaction.ticket_id)

        if ticket_type is not None:
            query = query.where(Ticket.ticket_type == ticket_type)

        if assigned_agent_id is not None:
            query = query.where(Ticket.agent_id == assigned_agent_id)

        if folder_id is not None:
            query = query.where(Interaction.folder_id == folder_id)

        query = query.where(
            Interaction.is_visible.is_(True),
            Interaction.interaction_type == "EMAIL",
            Interaction.parent_interaction_id.is_(None),
        )

        now = datetime.now(timezone.utc)

        if view == "pending":
            query = query.where(
                Interaction.ticket_id.is_(None),
                Interaction.status == InteractionStatus.PENDING,
                or_(
                    Interaction.snoozed_until.is_(None),
                    Interaction.snoozed_until <= now,
                ),
            )
        elif view == "snoozed":
            query = query.where(
                Interaction.ticket_id.is_(None),
                Interaction.status == InteractionStatus.PENDING,
                Interaction.snoozed_until.isnot(None),
                Interaction.snoozed_until > now,
            )
        elif view == "replied":
            query = query.where(
                Interaction.ticket_id.is_(None),
                Interaction.status == InteractionStatus.ASSIGNED,
            )
        elif view == "ticketed":
            query = query.where(Interaction.ticket_id.isnot(None))
        elif view == "archived":
            query = query.where(
                Interaction.ticket_id.is_(None),
                Interaction.status == InteractionStatus.IGNORED,
            )
        # view == "all": no further filter — every root email.

        query = query.order_by(Interaction.received_at.desc())

        result = await self.db.execute(query)

        return list(result.scalars().all())

    async def list_thread(
        self,
        root_interaction_id: UUID,
    ) -> list[Interaction]:
        """
        Every reply/follow-up filed under a thread root, oldest
        first — the conversation shown under an inbox email.
        """

        result = await self.db.execute(
            select(Interaction)
            .where(
                Interaction.parent_interaction_id == root_interaction_id,
                Interaction.is_visible.is_(True),
            )
            .order_by(Interaction.created_at.asc())
        )

        return list(result.scalars().all())

    async def list_sent(
        self,
        performed_by: UUID,
    ) -> list[Interaction]:
        """
        Every reply the given user has sent — pre-ticket or
        ticket-level alike, both created via the same REPLY/OUTBOUND
        shape (see `InteractionService.add_interaction_reply`/
        `add_reply`) — plus every brand-new Compose email they've
        authored (InteractionService.compose_email), which is itself
        a thread ROOT rather than a child. A sent reply's subject/
        client is resolved by the caller via `list_by_ids` on
        `parent_interaction_id`; a sent Compose root already carries
        its own subject/client on its own payload (see
        InboxService.get_sent's branch on `parent_interaction_id is
        None`).
        """

        result = await self.db.execute(
            select(Interaction)
            .where(
                or_(
                    Interaction.interaction_type == "REPLY",
                    and_(
                        Interaction.interaction_type == "EMAIL",
                        Interaction.parent_interaction_id.is_(None),
                    ),
                ),
                Interaction.direction == InteractionDirection.OUTBOUND,
                Interaction.performed_by == performed_by,
                Interaction.is_visible.is_(True),
            )
            .order_by(Interaction.created_at.desc())
        )

        return list(result.scalars().all())

    async def list_by_ids(
        self,
        interaction_ids: list[UUID],
    ) -> list[Interaction]:
        """Batch fetch — used to resolve a set of thread roots in one query."""

        if not interaction_ids:
            return []

        result = await self.db.execute(
            select(Interaction).where(Interaction.interaction_id.in_(interaction_ids))
        )

        return list(result.scalars().all())

    async def get_draft(
        self,
        root_interaction_id: UUID,
        performed_by: UUID,
    ) -> Interaction | None:
        """
        The given agent's active draft on this thread, if any — one
        active draft per thread per agent, so this is always at most
        one row.
        """

        result = await self.db.execute(
            select(Interaction).where(
                Interaction.parent_interaction_id == root_interaction_id,
                Interaction.performed_by == performed_by,
                Interaction.is_draft.is_(True),
                Interaction.is_visible.is_(True),
            )
        )

        return result.scalar_one_or_none()

    async def update_draft_message(
        self,
        interaction: Interaction,
        message: str,
        cc: list[str] | None = None,
        bcc: list[str] | None = None,
    ) -> Interaction:
        """Overwrites a draft's saved text (and Cc/Bcc) in place — upsert's "update" half."""

        interaction.payload = {
            **interaction.payload,
            "message": message,
            "cc": cc if cc is not None else interaction.payload.get("cc", []),
            "bcc": bcc if bcc is not None else interaction.payload.get("bcc", []),
        }

        await self.db.flush()
        await self.db.refresh(interaction)

        return interaction

    async def delete_draft(
        self,
        interaction: Interaction,
    ) -> None:
        """
        Hard-deletes a draft row. Unlike every other Interaction (soft-
        deleted via `hide`), a draft was never visible communication —
        nothing on the timeline/audit trail ever references it, so
        there's nothing a soft-delete would need to preserve.
        """

        await self.db.delete(interaction)
        await self.db.flush()

    async def list_drafts(
        self,
        performed_by: UUID,
    ) -> list[Interaction]:
        """Every draft the given agent currently has saved, across every thread."""

        result = await self.db.execute(
            select(Interaction)
            .where(
                Interaction.is_draft.is_(True),
                Interaction.performed_by == performed_by,
                Interaction.is_visible.is_(True),
            )
            .order_by(Interaction.created_at.desc())
        )

        return list(result.scalars().all())

    async def get_by_message_ids(
        self,
        message_ids: list[str],
    ) -> list[Interaction]:
        """
        Looks up interactions by their message_id — the thread-match
        step: an inbound email's In-Reply-To/References are checked
        against message_ids we've already stored (ours or the
        client's) to decide whether it's a new conversation or a
        continuation of one.
        """

        if not message_ids:
            return []

        result = await self.db.execute(
            select(Interaction).where(Interaction.message_id.in_(message_ids))
        )

        return list(result.scalars().all())

    async def get_by_conversation_id(
        self,
        conversation_id: str,
    ) -> list[Interaction]:
        """
        Looks up interactions by Graph's conversation_id — the
        highest-priority thread-match signal once Task 1 ships real
        Graph data (unused by the dummy-mail flow today, since
        nothing populates conversation_id yet).
        """

        result = await self.db.execute(
            select(Interaction).where(Interaction.conversation_id == conversation_id)
        )

        return list(result.scalars().all())

    async def list_thread_summaries(
        self,
        root_interaction_ids: list[UUID],
    ) -> dict[UUID, tuple[int, Interaction | None]]:
        """
        Batched "how many replies, and what's the latest one" lookup
        for a set of thread roots — used to populate the inbox list's
        reply_count/latest_* columns without an N+1 query per row.
        Returns {root_id: (reply_count, latest_reply_or_None)}; a
        root with zero replies is simply absent from the dict.
        """

        if not root_interaction_ids:
            return {}

        result = await self.db.execute(
            select(Interaction)
            .where(
                Interaction.parent_interaction_id.in_(root_interaction_ids),
                Interaction.is_visible.is_(True),
                Interaction.is_draft.is_(False),
            )
            .order_by(Interaction.created_at.asc())
        )

        summaries: dict[UUID, tuple[int, Interaction | None]] = {}
        for reply in result.scalars().all():
            root_id = reply.parent_interaction_id
            count, _latest = summaries.get(root_id, (0, None))
            # Rows arrive oldest-first, so the last one seen per root
            # is always the most recent — no separate max(created_at)
            # pass needed.
            summaries[root_id] = (count + 1, reply)

        return summaries

    async def assign_thread_to_ticket(
        self,
        root_interaction_id: UUID,
        ticket_id: UUID,
    ) -> None:
        """
        Moves an entire inbox thread (its root plus every reply
        filed under it) onto a ticket in one go — used when a
        pending email (or a whole conversation under it) is
        promoted to a ticket, so replies already exchanged before
        the ticket existed still show up on its timeline.
        """

        root = await self.get_by_id(root_interaction_id)
        if root is not None and root.ticket_id is None:
            root.ticket_id = ticket_id
            root.status = InteractionStatus.ASSIGNED

        thread = await self.list_thread(root_interaction_id)
        for reply in thread:
            reply.ticket_id = ticket_id
            reply.status = InteractionStatus.ASSIGNED

        await self.db.flush()

    async def get_latest_inbound_email_for_ticket(
        self,
        ticket_id: UUID,
    ) -> Interaction | None:
        """
        The most recent INBOUND email interaction on a ticket —
        used to build a reply's envelope (recipient address,
        In-Reply-To header) without the caller needing to know the
        ticket's email history.
        """

        result = await self.db.execute(
            select(Interaction)
            .where(
                Interaction.ticket_id == ticket_id,
                Interaction.interaction_type == "EMAIL",
            )
            .order_by(Interaction.created_at.desc())
            .limit(1)
        )

        return result.scalar_one_or_none()

    async def update(
        self,
        interaction: Interaction,
        data: InteractionUpdate,
    ) -> Interaction:

        update_data = data.model_dump(
            exclude_unset=True
        )

        for field, value in update_data.items():
            setattr(interaction, field, value)

        await self.db.flush()

        await self.db.refresh(interaction)

        return interaction

    async def assign_to_ticket(
        self,
        interaction: Interaction,
        ticket_id: UUID,
    ) -> Interaction:
        """
        Assign an inbox interaction to a ticket.

        Used when an agent creates a new ticket
        or attaches the email to an existing ticket.
        """

        interaction.ticket_id = ticket_id

        interaction.status = InteractionStatus.ASSIGNED

        await self.db.flush()

        await self.db.refresh(interaction)

        return interaction

    async def exists_by_message_id(
        self,
        message_id: str,
    ) -> bool:
        """
        Check whether an interaction with the given
        email message_id already exists.
        """

        result = await self.db.execute(
            select(Interaction.interaction_id).where(
                Interaction.message_id == message_id
            )
        )

        return result.scalar_one_or_none() is not None

    async def claim(
        self,
        interaction: Interaction,
        user_id: UUID,
    ) -> Interaction | None:
        """
        Atomically assigns an unclaimed, unticketed PENDING interaction
        to `user_id` — "Assign to me". Guarded by a conditional UPDATE
        (mirroring TicketRepository.claim's ticket-level race guard)
        rather than a plain ORM attribute set, so two agents clicking
        "Assign to me" on the same item at the same moment can't both
        win. Returns None when the guard fails (already claimed,
        already ticketed, or no longer pending).
        """

        result = await self.db.execute(
            update(Interaction)
            .where(
                Interaction.interaction_id == interaction.interaction_id,
                Interaction.ticket_id.is_(None),
                Interaction.status == InteractionStatus.PENDING,
                Interaction.claimed_by.is_(None),
            )
            .values(claimed_by=user_id, claimed_at=datetime.now(timezone.utc))
        )

        if result.rowcount == 0:
            return None

        await self.db.flush()
        await self.db.refresh(interaction)

        return interaction

    async def archive(
        self,
        interaction: Interaction,
    ) -> Interaction | None:
        """
        Atomically marks a pending, unticketed interaction IGNORED —
        the "Informational / Archive" reviewer decision: store it, no
        ticket, no work assignment, still searchable later via the
        "archived" inbox view. Same conditional-UPDATE race guard as
        claim, so an archive and a concurrent claim/convert-to-ticket
        can't both silently win.
        """

        result = await self.db.execute(
            update(Interaction)
            .where(
                Interaction.interaction_id == interaction.interaction_id,
                Interaction.ticket_id.is_(None),
                Interaction.status == InteractionStatus.PENDING,
            )
            .values(status=InteractionStatus.IGNORED)
        )

        if result.rowcount == 0:
            return None

        await self.db.flush()
        await self.db.refresh(interaction)

        return interaction

    async def snooze(
        self,
        interaction: Interaction,
        snooze_until: datetime,
    ) -> Interaction | None:
        """
        Atomically hides a pending, unticketed interaction from the
        "pending" view until `snooze_until` — same conditional-UPDATE
        race guard as claim/archive, so a snooze racing a concurrent
        claim/convert-to-ticket can't silently win.
        """

        result = await self.db.execute(
            update(Interaction)
            .where(
                Interaction.interaction_id == interaction.interaction_id,
                Interaction.ticket_id.is_(None),
                Interaction.status == InteractionStatus.PENDING,
            )
            .values(snoozed_until=snooze_until)
        )

        if result.rowcount == 0:
            return None

        await self.db.flush()
        await self.db.refresh(interaction)

        return interaction

    async def unsnooze(
        self,
        interaction: Interaction,
    ) -> Interaction | None:
        """
        Clears an active snooze early, returning the item to
        "pending" immediately. Guarded on `snoozed_until IS NOT NULL`
        so calling this on an item that was never snoozed (or whose
        snooze already lapsed and was cleared) is a clean no-op 409,
        not a silent success.
        """

        result = await self.db.execute(
            update(Interaction)
            .where(
                Interaction.interaction_id == interaction.interaction_id,
                Interaction.snoozed_until.isnot(None),
            )
            .values(snoozed_until=None)
        )

        if result.rowcount == 0:
            return None

        await self.db.flush()
        await self.db.refresh(interaction)

        return interaction

    async def set_tags(
        self,
        interaction: Interaction,
        tags: list[str],
    ) -> Interaction:
        """
        Full-replace of an interaction's tag list — no per-tag
        add/remove endpoint, the frontend always sends the complete
        set. Plain update, not a claim-style guard: tagging isn't a
        contested "only one winner" action the way claiming is.
        """

        interaction.tags = tags

        await self.db.flush()
        await self.db.refresh(interaction)

        return interaction

    async def set_folder(
        self,
        interaction: Interaction,
        folder_id: UUID | None,
    ) -> Interaction:
        """
        Assigns (or clears, if `folder_id` is None) which custom
        folder this item is filed under. Plain update — filing into a
        folder isn't a race-sensitive action.
        """

        interaction.folder_id = folder_id

        await self.db.flush()
        await self.db.refresh(interaction)

        return interaction

    async def hide(
        self,
        interaction: Interaction,
        removed_by: UUID | None,
    ) -> Interaction:
        """
        Soft-deletes an interaction.

        The interaction row is never removed from the
        database; it is simply marked as not visible,
        preserving the full ticket timeline and audit trail.
        """

        interaction.is_visible = False

        interaction.removed_by = removed_by

        interaction.removed_at = datetime.now(timezone.utc)

        await self.db.flush()

        await self.db.refresh(interaction)

        return interaction