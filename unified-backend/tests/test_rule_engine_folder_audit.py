# test_rule_engine_folder_audit.py
#
# Regression coverage for a Phase 1 addition (see the approved
# "Conversation/Thread Event Model" plan): a Rule's move_to_folder
# action previously left literally no record anywhere — not an
# Interaction, not an AuditLog row, just a log line. It now writes an
# INTERACTION_FOLDER_CHANGED AuditLog row, mirroring the manual
# PATCH /inbox/{id}/folder path (InteractionService.
# set_interaction_folder), attributed to the rule's own creator (or
# "System" if the rule has no creator) via the same
# AuditLogService.resolve_agent_actor helper RuleEngineService.
# _forward_to_employees already uses. This is deliberately
# AuditLog-only — never a Mail conversation bubble.
#
# (The companion forward_to/rule_name addition is covered separately
# in test_rule_engine_forward.py's pure-logic style, since exercising
# it through this file's real-DB pipeline would trigger a real
# outbound Graph send in this environment — real Graph credentials are
# configured here.)
#
# Runs against the real (dev) database inside a transaction that is
# always rolled back at the end — same convention as
# test_rule_engine_transaction_isolation.py / test_rule_delete_folder_cleanup.py.

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import select
from shared_models.models import Role, User

from app.database.session import AsyncSessionLocal, engine
from app.ticketing.enums import AuditEntityType, AuditEventType, InteractionDirection, InteractionStatus
from app.ticketing.models.audit_log import AuditLog
from app.ticketing.models.interaction import Interaction
from app.ticketing.models.rule import Rule
from app.notifications.repository import NotificationRepository
from app.notifications.service import NotificationService
from app.ticketing.repositories.distribution_list_repository import (
    DistributionListRepository,
)
from app.ticketing.repositories.interaction_repository import InteractionRepository
from app.ticketing.repositories.mail_folder_repository import MailFolderRepository
from app.ticketing.repositories.rule_repository import RuleRepository
from app.ticketing.repositories.user_repository import UserRepository
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


async def _get_active_user(session) -> User:
    result = await session.execute(
        select(User).where(User.is_active.is_(True)).limit(1)
    )
    user = result.scalars().first()
    if user is None:
        pytest.skip("No active seeded user found to use as a rule creator.")
    return user


def _build_service(session) -> RuleEngineService:
    return RuleEngineService(
        rule_repository=RuleRepository(session),
        mail_folder_repository=MailFolderRepository(session),
        interaction_repository=InteractionRepository(session),
        user_repository=UserRepository(session),
        notification_service=NotificationService(NotificationRepository(session)),
        distribution_list_repository=DistributionListRepository(session),
    )


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


def _folder_rule(*, created_by, subject_token: str, folder_name: str) -> Rule:
    return Rule(
        rule_id=uuid.uuid4(),
        name=f"Folder audit test rule {uuid.uuid4().hex[:8]}",
        category="mail_rule",
        is_enabled=True,
        conditions={
            "combinator": "AND",
            "rules": [
                {"field": "subject_contains", "operator": "contains", "value": subject_token}
            ],
        },
        exceptions={"combinator": "AND", "rules": []},
        actions=[{"type": "move_to_folder", "folder_name": folder_name}],
        priority=1,
        created_by=created_by,
    )


async def test_rule_driven_folder_move_writes_audit_log_attributed_to_creator(db_session):
    creator = await _get_active_user(db_session)
    subject_token = f"FolderAudit-{uuid.uuid4().hex[:8]}"
    folder_name = f"Folder Audit Test {uuid.uuid4().hex[:8]}"

    interaction = await _make_pending_interaction(db_session, subject=f"{subject_token} email")
    rule = _folder_rule(created_by=creator.user_id, subject_token=subject_token, folder_name=folder_name)
    db_session.add(rule)
    await db_session.flush()

    service = _build_service(db_session)
    context = RuleEmailContext(
        from_email="client@example.com",
        subject=interaction.subject,
        body="Test body",
        client_id=None,
    )

    await service.evaluate_and_execute_for_email(interaction=interaction, context=context)

    await db_session.refresh(interaction)
    assert interaction.folder_id is not None

    result = await db_session.execute(
        select(AuditLog).where(
            AuditLog.entity_type == AuditEntityType.INTERACTION,
            AuditLog.entity_id == interaction.interaction_id,
            AuditLog.event_type == AuditEventType.INTERACTION_FOLDER_CHANGED,
        )
    )
    logs = result.scalars().all()
    assert len(logs) == 1
    log = logs[0]
    assert log.actor_id == creator.user_id
    assert log.actor_name == creator.name
    assert log.new_values["folder_id"] == str(interaction.folder_id)
    assert log.new_values["rule_id"] == str(rule.rule_id)


async def test_rule_driven_folder_move_falls_back_to_system_when_rule_has_no_creator(db_session):
    subject_token = f"FolderAuditNoCreator-{uuid.uuid4().hex[:8]}"
    folder_name = f"Folder Audit No Creator Test {uuid.uuid4().hex[:8]}"

    interaction = await _make_pending_interaction(db_session, subject=f"{subject_token} email")
    rule = _folder_rule(created_by=None, subject_token=subject_token, folder_name=folder_name)
    db_session.add(rule)
    await db_session.flush()

    service = _build_service(db_session)
    context = RuleEmailContext(
        from_email="client@example.com",
        subject=interaction.subject,
        body="Test body",
        client_id=None,
    )

    await service.evaluate_and_execute_for_email(interaction=interaction, context=context)

    result = await db_session.execute(
        select(AuditLog).where(
            AuditLog.entity_type == AuditEntityType.INTERACTION,
            AuditLog.entity_id == interaction.interaction_id,
            AuditLog.event_type == AuditEventType.INTERACTION_FOLDER_CHANGED,
        )
    )
    log = result.scalars().one()
    assert log.actor_id is None
    assert log.actor_name == "System"
