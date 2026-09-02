# test_rule_engine_transaction_isolation.py
#
# Regression coverage for the P0 fix: a rule action's own DB-level
# failure (most plausibly a folder-name create race — two rules
# matching two near-simultaneous inbound emails, both naming a
# brand-new folder) must never poison the surrounding transaction and
# silently drop the whole inbound email (ticket/interaction included)
# along with it. Two layers were fixed and are each covered here:
#
# 1. rule_folder_sync.ensure_folder is now race-safe on its own — a
#    lost create race is caught and resolved by re-fetching the
#    winner's row, never propagating IntegrityError at all in the
#    common case this bug actually reproduces from.
# 2. RuleEngineService._execute_action's own call is now wrapped in a
#    savepoint (db.begin_nested()) as defense-in-depth — even a DB
#    error ensure_folder's own fix doesn't cover must only roll back
#    to the savepoint, leaving every later statement in the same
#    request (remaining rules, the caller's own commit of the
#    already-created Interaction) unaffected.
#
# Runs against the real (dev) database inside a transaction that is
# always rolled back at the end — same convention as
# test_rule_delete_folder_cleanup.py.

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy.exc import IntegrityError

from app.database.session import AsyncSessionLocal, engine
from app.notifications.repository import NotificationRepository
from app.notifications.service import NotificationService
from app.ticketing.enums import InteractionDirection, InteractionStatus
from app.ticketing.models.interaction import Interaction
from app.ticketing.models.mail_folder import MailFolder
from app.ticketing.repositories.distribution_list_repository import (
    DistributionListRepository,
)
from app.ticketing.repositories.interaction_repository import InteractionRepository
from app.ticketing.repositories.mail_folder_repository import MailFolderRepository
from app.ticketing.repositories.rule_repository import RuleRepository
from app.ticketing.repositories.user_repository import UserRepository
from app.ticketing.services import rule_folder_sync
from app.ticketing.services.rule_conditions import RuleEmailContext
from app.ticketing.services.rule_engine_service import RuleEngineService


@pytest.fixture
async def db_session():
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.rollback()
    await engine.dispose()


async def _make_pending_interaction(session, *, subject: str) -> Interaction:
    interaction = Interaction(
        interaction_id=uuid.uuid4(),
        interaction_type="EMAIL",
        direction=InteractionDirection.INBOUND,
        status=InteractionStatus.PENDING,
        payload={"subject": subject, "body": "Test body", "from_email": "client@example.com"},
        message_id=f"<{uuid.uuid4().hex}@example.com>",
        is_visible=True,
        subject=subject,
        received_at=datetime.now(timezone.utc),
    )
    session.add(interaction)
    await session.flush()
    return interaction


def _build_service(session) -> RuleEngineService:
    return RuleEngineService(
        rule_repository=RuleRepository(session),
        mail_folder_repository=MailFolderRepository(session),
        interaction_repository=InteractionRepository(session),
        user_repository=UserRepository(session),
        notification_service=NotificationService(NotificationRepository(session)),
        distribution_list_repository=DistributionListRepository(session),
    )


async def test_ensure_folder_recovers_from_a_concurrent_create_race(db_session):
    """
    Simulates the actual race: a folder with this name already exists
    (created a moment ago by a "concurrent" request this call's own
    get_by_name check never saw), so the real create() attempt inside
    ensure_folder hits the unique-constraint violation for real. Must
    resolve to the winner's row, not raise.
    """

    name = f"Race Folder {uuid.uuid4().hex[:8]}"
    repository = MailFolderRepository(db_session)

    winner = MailFolder(name=name, created_by=None, is_rule_created=True)
    db_session.add(winner)
    await db_session.flush()

    call_count = {"n": 0}
    original_get_by_name = repository.get_by_name

    async def _get_by_name_missing_first_time(lookup_name):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return None
        return await original_get_by_name(lookup_name)

    repository.get_by_name = _get_by_name_missing_first_time  # type: ignore[method-assign]

    result = await rule_folder_sync.ensure_folder(
        name, created_by=None, mail_folder_repository=repository
    )

    assert result.folder_id == winner.folder_id
    # Only one MailFolder with this name exists — the race did not
    # produce a duplicate, and the loser's failed create() didn't
    # leave the session in a broken state either.
    fresh = await original_get_by_name(name)
    assert fresh is not None
    assert fresh.folder_id == winner.folder_id


async def test_action_db_failure_does_not_poison_the_session_for_later_statements(
    db_session, monkeypatch
):
    """
    Forces a genuine DB-level IntegrityError (not just a Python
    exception) inside _execute_action's own call, via a savepoint-
    wrapped duplicate-unique-key insert, and confirms the surrounding
    session is still perfectly usable afterward — flushing the
    already-created Interaction's own further changes, exactly what
    the real bug this fix targets would otherwise have broken.
    """

    interaction = await _make_pending_interaction(db_session, subject="Isolation test")

    service = _build_service(db_session)

    async def _boom_with_a_real_db_error(action, *, interaction, rule, **_kwargs):
        dup = Interaction(
            interaction_id=uuid.uuid4(),
            interaction_type="EMAIL",
            direction=InteractionDirection.INBOUND,
            status=InteractionStatus.PENDING,
            payload={},
            # Duplicates the outer interaction's own message_id — a
            # real unique-constraint violation at flush time, not a
            # simulated one.
            message_id=interaction.message_id,
        )
        db_session.add(dup)
        await db_session.flush()

    monkeypatch.setattr(service, "_execute_action", _boom_with_a_real_db_error)

    class _FakeRule:
        rule_id = uuid.uuid4()
        name = "Isolation test rule"
        category = "mail_rule"
        conditions = {
            "combinator": "AND",
            "rules": [
                {"field": "subject_contains", "operator": "contains", "value": "Isolation"}
            ],
        }
        exceptions = {"combinator": "AND", "rules": []}
        actions = [{"type": "move_to_folder", "folder_name": "Whatever"}]
        stop_processing = False
        created_by = None

    async def _list_enabled_ordered():
        return [_FakeRule()]

    monkeypatch.setattr(service.rule_repository, "list_enabled_ordered", _list_enabled_ordered)

    context = RuleEmailContext(
        from_email="client@example.com",
        subject="Isolation test",
        body="Test body",
        client_id=None,
    )

    # Must not raise — the action's own real IntegrityError is caught
    # and contained to its own savepoint.
    await service.evaluate_and_execute_for_email(interaction=interaction, context=context)

    # The session must still be perfectly usable: a genuinely new
    # statement (updating the outer interaction) must succeed, not
    # raise PendingRollbackError the way it would have before this fix
    # (every statement after an unrecovered flush failure raises,
    # including the caller's own eventual commit of this same row).
    interaction.subject = "Isolation test — updated after action failure"
    await db_session.flush()

    refreshed = await db_session.get(Interaction, interaction.interaction_id)
    assert refreshed is not None
    assert refreshed.subject == "Isolation test — updated after action failure"
