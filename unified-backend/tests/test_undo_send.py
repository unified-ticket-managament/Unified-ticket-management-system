# test_undo_send.py
#
# Regression coverage for Issue 8 (real, server-enforced 10-second
# Undo Send window for Compose and both Reply paths):
#
#   - InteractionService._schedule_delayed_send now runs in place of
#     every synchronous `_dispatch_and_record` call site — it commits
#     the interaction as dispatch_status="PENDING_SEND" with a real
#     send_after timestamp, then schedules the actual send via
#     undo_send.schedule_delayed_send (a fire-and-forget
#     asyncio.create_task, mirroring app.notifications.email_notifier's
#     own established pattern).
#   - InteractionService.cancel_pending_send is the one cancellation
#     path for all outbound sends — authorization (only the original
#     sender), the real deadline check, and idempotency all live here,
#     never trusted to the frontend's own countdown timer.
#   - undo_send._dispatch_if_still_pending is the real (awaitable,
#     testable-without-sleeping) dispatch logic the background task
#     eventually runs — re-checks dispatch_status fresh from the DB
#     before ever actually sending, so a cancellation that lands after
#     scheduling but before the delay elapses is never missed.
#
# Runs against the real (dev) database inside a transaction that is
# always rolled back at the end — same convention as
# test_ticket_status_on_assignment.py. The mail provider itself is
# whatever get_mail_provider_client() resolves to in this environment
# (MockMailProviderClient, per app.ticketing.services.mail_provider,
# since no real Graph credentials are configured here) — a real send
# never actually leaves this machine.

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from sqlalchemy import delete, select
from sqlalchemy.orm import joinedload
from shared_models.models import Role, User

from app.database.session import AsyncSessionLocal, engine
from app.ticketing.enums import InteractionDirection
from app.ticketing.models.interaction import Interaction
from app.ticketing.repositories.interaction_repository import InteractionRepository
from app.ticketing.repositories.ticket_repository import TicketRepository
from app.ticketing.repositories.user_repository import UserRepository
from app.ticketing.schemas.interaction import InteractionCreate
from app.ticketing.schemas.payloads import OutboundEnvelope
from app.ticketing.services.interaction_service import InteractionService
from app.ticketing.services.undo_send import _dispatch_if_still_pending


@pytest.fixture
async def db_session():
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.rollback()
    await engine.dispose()


async def _get_user_by_role(session, role_name: str) -> User:
    result = await session.execute(
        select(User)
        .options(joinedload(User.role))
        .join(Role, Role.role_id == User.role_id)
        .where(Role.name == role_name, User.is_active.is_(True))
    )
    users = result.unique().scalars().all()
    if users:
        return users[0]
    pytest.skip(f"No active seeded {role_name!r} found.")


def _build_service(session) -> InteractionService:
    return InteractionService(
        interaction_repository=InteractionRepository(session),
        ticket_repository=TicketRepository(session),
        user_repository=UserRepository(session),
    )


def _make_envelope(to_email: str = "client@example.com") -> OutboundEnvelope:
    return OutboundEnvelope(
        from_email="support@probeps.com",
        from_name="Support",
        to_email=to_email,
        subject="Undo-send test",
        message_id=f"<{uuid.uuid4().hex}@probeps.com>",
        body="This is a test message.",
    )


async def _make_pending_interaction(
    session,
    *,
    performed_by,
    dispatch_status: str = "PENDING_SEND",
    send_after: datetime | None = None,
) -> Interaction:
    repository = InteractionRepository(session)
    payload: dict = {"message": "Undo-send test body", "dispatch_status": dispatch_status}
    if send_after is not None:
        payload["send_after"] = send_after.isoformat()

    return await repository.create(
        InteractionCreate(
            ticket_id=None,
            interaction_type="REPLY",
            direction=InteractionDirection.OUTBOUND,
            performed_by=performed_by,
            payload=payload,
        )
    )


# ---------------------------------------------------------------
# cancel_pending_send — authorization, deadline, idempotency.
# ---------------------------------------------------------------


async def test_cancel_within_window_succeeds_and_marks_canceled(db_session):
    sender = await _get_user_by_role(db_session, "Staff")
    send_after = datetime.now(timezone.utc) + timedelta(seconds=10)
    interaction = await _make_pending_interaction(
        db_session, performed_by=sender.user_id, send_after=send_after
    )

    # cancel_pending_send commits internally on success (it must — the
    # background dispatch task reads from a completely different
    # session/connection and needs to durably see the cancellation) —
    # which takes this row outside the fixture's own rolled-back-
    # transaction convention, so it's deleted explicitly afterward.
    try:
        service = _build_service(db_session)
        response = await service.cancel_pending_send(interaction.interaction_id, sender)

        assert response.interaction_id == interaction.interaction_id
        await db_session.refresh(interaction)
        assert interaction.payload["dispatch_status"] == "CANCELED"
    finally:
        await _delete_interaction(db_session, interaction.interaction_id)


async def test_cancel_just_before_the_deadline_still_succeeds(db_session):
    """
    Case B from the Issue 8 spec: Undo clicked just before the
    deadline. Uses a few real seconds of margin rather than
    milliseconds — this suite's own DB round-trips against the shared
    Neon database routinely take several hundred ms each (see this
    repo's own CLAUDE.md performance notes), so a sub-second window
    would make this test itself the flaky part, not the feature.
    """

    sender = await _get_user_by_role(db_session, "Staff")
    send_after = datetime.now(timezone.utc) + timedelta(seconds=5)
    interaction = await _make_pending_interaction(
        db_session, performed_by=sender.user_id, send_after=send_after
    )

    # See the previous test's comment — cancel_pending_send commits
    # internally on success, so this row needs explicit cleanup too.
    try:
        service = _build_service(db_session)
        response = await service.cancel_pending_send(interaction.interaction_id, sender)
        assert response.interaction_id == interaction.interaction_id
    finally:
        await _delete_interaction(db_session, interaction.interaction_id)


async def test_cancel_after_window_expired_is_rejected(db_session):
    """Case C from the Issue 8 spec: Undo clicked after the deadline."""

    sender = await _get_user_by_role(db_session, "Staff")
    send_after = datetime.now(timezone.utc) - timedelta(seconds=1)
    interaction = await _make_pending_interaction(
        db_session, performed_by=sender.user_id, send_after=send_after
    )

    service = _build_service(db_session)
    with pytest.raises(HTTPException) as exc_info:
        await service.cancel_pending_send(interaction.interaction_id, sender)
    assert exc_info.value.status_code == 400

    # The rejection must not silently cancel it anyway.
    reloaded = await InteractionRepository(db_session).get_by_id(interaction.interaction_id)
    assert reloaded.payload["dispatch_status"] == "PENDING_SEND"


async def test_cancel_by_a_different_user_is_forbidden(db_session):
    sender = await _get_user_by_role(db_session, "Staff")
    other_user = await _get_user_by_role(db_session, "Team Lead")
    send_after = datetime.now(timezone.utc) + timedelta(seconds=10)
    interaction = await _make_pending_interaction(
        db_session, performed_by=sender.user_id, send_after=send_after
    )

    service = _build_service(db_session)
    with pytest.raises(HTTPException) as exc_info:
        await service.cancel_pending_send(interaction.interaction_id, other_user)
    assert exc_info.value.status_code == 403

    reloaded = await InteractionRepository(db_session).get_by_id(interaction.interaction_id)
    assert reloaded.payload["dispatch_status"] == "PENDING_SEND"


async def test_cancel_twice_is_idempotent(db_session):
    """Case G from the Issue 8 spec: clicking Undo twice must be safe."""

    sender = await _get_user_by_role(db_session, "Staff")
    send_after = datetime.now(timezone.utc) + timedelta(seconds=10)
    interaction = await _make_pending_interaction(
        db_session, performed_by=sender.user_id, send_after=send_after
    )

    # The first cancel_pending_send call commits internally on
    # success, taking this row outside the fixture's rolled-back-
    # transaction convention — cleaned up explicitly afterward.
    try:
        service = _build_service(db_session)
        first = await service.cancel_pending_send(interaction.interaction_id, sender)
        assert first.message == "Send canceled."

        with pytest.raises(HTTPException) as exc_info:
            await service.cancel_pending_send(interaction.interaction_id, sender)
        assert exc_info.value.status_code == 400

        reloaded = await InteractionRepository(db_session).get_by_id(interaction.interaction_id)
        assert reloaded.payload["dispatch_status"] == "CANCELED"
    finally:
        await _delete_interaction(db_session, interaction.interaction_id)


async def test_cancel_an_already_sent_message_is_rejected(db_session):
    """Case I from the Issue 8 spec: never claim success once dispatched."""

    sender = await _get_user_by_role(db_session, "Staff")
    interaction = await _make_pending_interaction(
        db_session, performed_by=sender.user_id, dispatch_status="SENT"
    )

    service = _build_service(db_session)
    with pytest.raises(HTTPException) as exc_info:
        await service.cancel_pending_send(interaction.interaction_id, sender)
    assert exc_info.value.status_code == 400


async def test_cancel_nonexistent_interaction_404s(db_session):
    sender = await _get_user_by_role(db_session, "Staff")
    service = _build_service(db_session)
    with pytest.raises(HTTPException) as exc_info:
        await service.cancel_pending_send(uuid.uuid4(), sender)
    assert exc_info.value.status_code == 404


# ---------------------------------------------------------------
# The real (delayed) dispatch logic — tested directly, without
# sleeping, per email_notifier.py's own established convention of
# separating the awaitable real logic from its fire-and-forget wrapper.
# ---------------------------------------------------------------


async def _delete_interaction(session, interaction_id) -> None:
    # _dispatch_if_still_pending opens its own independently-committed
    # session (by design — see its own docstring), so any test driving
    # it must commit the interaction first for that session to see it.
    # That takes the row outside this file's usual rolled-back-
    # transaction convention, so it's explicitly deleted (and that
    # deletion committed) afterward instead.
    await session.execute(delete(Interaction).where(Interaction.interaction_id == interaction_id))
    await session.commit()


async def test_dispatch_if_still_pending_sends_when_not_canceled(db_session):
    sender = await _get_user_by_role(db_session, "Staff")
    interaction = await _make_pending_interaction(db_session, performed_by=sender.user_id)
    await db_session.commit()

    try:
        envelope = _make_envelope()
        await _dispatch_if_still_pending(interaction.interaction_id, envelope)

        # refresh() (awaited, not expire_all()) is required here:
        # db_session already holds this row in its own identity map
        # from creating it above, and _dispatch_if_still_pending
        # committed the real change through a completely different
        # session/connection — without an awaited refresh, accessing
        # this object's attributes afterward would either return the
        # stale cached copy, or (once expired) raise MissingGreenlet
        # from trying to lazy-load outside an awaited context.
        await db_session.refresh(interaction)
        reloaded = interaction
        assert reloaded.payload["dispatch_status"] == "SENT"
        # provider_message_id is deliberately NOT asserted truthy here:
        # a plain sendMail/reply send (this envelope has no
        # reply_to_provider_message_id, so it's sendMail) correctly
        # returns None — Graph gives no real id back synchronously,
        # and this platform must never substitute its own
        # envelope.message_id as a stand-in (see
        # MailProviderSendResult's own docstring). The key it does
        # need to carry either way:
        assert "provider_message_id" in reloaded.payload
    finally:
        await _delete_interaction(db_session, interaction.interaction_id)


async def test_dispatch_if_still_pending_skips_when_canceled(db_session):
    """
    The core race the whole feature exists to close: a cancellation
    that landed before the delayed task woke up must never be
    overridden by a send that happens anyway.
    """

    sender = await _get_user_by_role(db_session, "Staff")
    interaction = await _make_pending_interaction(
        db_session, performed_by=sender.user_id, dispatch_status="CANCELED"
    )
    await db_session.commit()

    try:
        envelope = _make_envelope()
        await _dispatch_if_still_pending(interaction.interaction_id, envelope)

        # refresh() (awaited, not expire_all()) is required here:
        # db_session already holds this row in its own identity map
        # from creating it above, and _dispatch_if_still_pending
        # committed the real change through a completely different
        # session/connection — without an awaited refresh, accessing
        # this object's attributes afterward would either return the
        # stale cached copy, or (once expired) raise MissingGreenlet
        # from trying to lazy-load outside an awaited context.
        await db_session.refresh(interaction)
        reloaded = interaction
        # Still CANCELED — never flipped to SENT, and no
        # provider_message_id was ever attached.
        assert reloaded.payload["dispatch_status"] == "CANCELED"
        assert "provider_message_id" not in reloaded.payload
    finally:
        await _delete_interaction(db_session, interaction.interaction_id)


async def test_dispatch_if_still_pending_is_a_noop_for_already_sent(db_session):
    sender = await _get_user_by_role(db_session, "Staff")
    interaction = await _make_pending_interaction(
        db_session, performed_by=sender.user_id, dispatch_status="SENT"
    )
    await db_session.commit()

    try:
        envelope = _make_envelope()
        await _dispatch_if_still_pending(interaction.interaction_id, envelope)

        # refresh() (awaited, not expire_all()) is required here:
        # db_session already holds this row in its own identity map
        # from creating it above, and _dispatch_if_still_pending
        # committed the real change through a completely different
        # session/connection — without an awaited refresh, accessing
        # this object's attributes afterward would either return the
        # stale cached copy, or (once expired) raise MissingGreenlet
        # from trying to lazy-load outside an awaited context.
        await db_session.refresh(interaction)
        reloaded = interaction
        assert reloaded.payload["dispatch_status"] == "SENT"
    finally:
        await _delete_interaction(db_session, interaction.interaction_id)
