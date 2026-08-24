# test_rule_delete_folder_cleanup.py
#
# Regression coverage for a real reported bug: deleting a Mail/OTP
# Rule whose action files mail into a folder that still holds real
# Interaction rows crashed with an unhandled 500
# (asyncpg.exceptions.ForeignKeyViolationError on
# interactions_folder_id_fkey) — the browser reported this as a CORS
# failure (no error-response CORS headers), masking the real cause.
#
# RuleService.delete's folder-cleanup step deleted a no-longer-
# referenced folder unconditionally, never checking whether any real
# message was still filed into it. Fixed by guarding that delete with
# InteractionRepository.has_any_interaction_in_folder — a folder still
# holding real messages is now left in place (an ordinary, rule-less
# folder) instead of crashing the whole rule-delete request.
#
# Runs against the real (dev) database inside a transaction that is
# always rolled back at the end — same convention as
# test_inbox_ticket_service.py / test_folder_sharing_visibility.py.

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import select
from shared_models.models import Role, User

from app.database.session import AsyncSessionLocal, engine
from app.ticketing.enums import InteractionDirection, InteractionStatus
from app.ticketing.models.client import Client
from app.ticketing.models.interaction import Interaction
from app.ticketing.repositories.interaction_repository import InteractionRepository
from app.ticketing.repositories.mail_folder_repository import MailFolderRepository
from app.ticketing.repositories.rule_repository import RuleRepository
from app.ticketing.schemas.rule import RuleActionItem, RuleConditionGroup, RuleCreate
from app.ticketing.services.rule_service import RuleService


@pytest.fixture
async def db_session():
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.rollback()
    await engine.dispose()


async def _get_super_admin(session) -> User:
    result = await session.execute(
        select(User)
        .join(Role, Role.role_id == User.role_id)
        .where(Role.name == "Super Admin", User.is_active.is_(True))
    )
    admin = result.scalars().first()
    if admin is None:
        pytest.skip("No active seeded Super Admin found.")
    return admin


async def _make_client(session, *, account_manager_id) -> Client:
    client = Client(
        client_id=uuid.uuid4(),
        name="Rule Delete Test Client",
        inbox_email=f"rule-delete-test-{uuid.uuid4().hex[:8]}@example.com",
        account_manager_id=account_manager_id,
        is_active=True,
    )
    session.add(client)
    await session.flush()
    return client


async def _make_email(session, *, client_id, folder_id) -> Interaction:
    interaction = Interaction(
        interaction_id=uuid.uuid4(),
        interaction_type="EMAIL",
        direction=InteractionDirection.INBOUND,
        status=InteractionStatus.PENDING,
        payload={
            "subject": "Test",
            "body": "Test body",
            "from_email": "client@example.com",
            "to_email": "support@probeps.com",
            "client_name": "Rule Delete Test Client",
        },
        parent_interaction_id=None,
        ticket_id=None,
        client_id=client_id,
        folder_id=folder_id,
        is_visible=True,
        subject="Test",
        received_at=datetime.now(timezone.utc),
    )
    session.add(interaction)
    await session.flush()
    return interaction


def _build_service(session) -> RuleService:
    return RuleService(
        RuleRepository(session),
        MailFolderRepository(session),
        InteractionRepository(session),
    )


async def _create_folder_rule(service, *, folder_name: str, current_user: User):
    request = RuleCreate(
        name=f"Rule delete test {uuid.uuid4().hex[:8]}",
        category="mail_rule",
        is_enabled=True,
        conditions=RuleConditionGroup.model_validate(
            {
                "combinator": "AND",
                "rules": [
                    {
                        "field": "sender_domain",
                        "operator": "equals",
                        "value": "never-real-domain.example",
                    }
                ],
            }
        ),
        exceptions=RuleConditionGroup.model_validate({"combinator": "AND", "rules": []}),
        actions=[RuleActionItem.model_validate({"type": "create_folder", "folder_name": folder_name})],
        stop_processing=False,
        shared_user_ids=[],
    )
    return await service.create(request, current_user=current_user)


async def test_delete_rule_preserves_folder_still_holding_real_messages(db_session):
    admin = await _get_super_admin(db_session)
    admin.permissions = ["rule:manage"]
    client = await _make_client(db_session, account_manager_id=admin.user_id)

    service = _build_service(db_session)
    folder_name = f"Rule Delete Test Folder {uuid.uuid4().hex[:8]}"
    rule = await _create_folder_rule(service, folder_name=folder_name, current_user=admin)

    folder_repository = MailFolderRepository(db_session)
    folder = await folder_repository.get_by_name(folder_name)
    assert folder is not None

    # A real message is filed into the folder — exactly the state that
    # used to crash delete() with a ForeignKeyViolationError.
    email = await _make_email(db_session, client_id=client.client_id, folder_id=folder.folder_id)

    # Must not raise.
    await service.delete(rule.rule_id, current_user=admin)

    # The rule itself is gone...
    assert await RuleRepository(db_session).get_by_id(rule.rule_id) is None

    # ...but the folder survives, since it still holds a real message.
    surviving_folder = await folder_repository.get_by_name(folder_name)
    assert surviving_folder is not None
    assert surviving_folder.folder_id == folder.folder_id

    # ...and the message itself was never touched.
    reloaded_email = await InteractionRepository(db_session).get_by_id(email.interaction_id)
    assert reloaded_email is not None
    assert reloaded_email.folder_id == folder.folder_id


async def test_delete_rule_still_removes_folder_with_no_messages(db_session):
    admin = await _get_super_admin(db_session)
    admin.permissions = ["rule:manage"]

    service = _build_service(db_session)
    folder_name = f"Rule Delete Test Empty Folder {uuid.uuid4().hex[:8]}"
    rule = await _create_folder_rule(service, folder_name=folder_name, current_user=admin)

    folder_repository = MailFolderRepository(db_session)
    assert await folder_repository.get_by_name(folder_name) is not None

    await service.delete(rule.rule_id, current_user=admin)

    # No messages were ever filed into it — the original, unaffected
    # cleanup behavior: the folder is actually deleted.
    assert await folder_repository.get_by_name(folder_name) is None
