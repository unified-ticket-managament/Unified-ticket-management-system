# test_distribution_list_folder_sharing.py
#
# DB-required regression/verification coverage for Mail Rule "Shared
# With -> Distribution List" — the specific path a live-UI report
# claimed was broken (a DL member did not get the expected shared
# folder/routed mail). test_rule_access_folder_sharing.py already
# covers the underlying can_view_rule/has_folder_share_access logic in
# isolation with fake objects and a hand-passed
# user_distribution_list_ids list; this file is the missing piece —
# the real DB path (DistributionList/DistributionListMember rows,
# DistributionListRepository.list_active_list_ids_for_user, real
# RuleService persistence) had never actually been exercised together
# end-to-end before this pass. Same real-DB-inside-a-rolled-back-
# transaction convention as test_folder_sharing_visibility.py.

import uuid
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import joinedload
from shared_models.models import Role, User

from app.database.session import AsyncSessionLocal, engine
from app.ticketing.enums import InteractionDirection, InteractionStatus
from app.ticketing.models.client import Client
from app.ticketing.models.distribution_list import DistributionList, DistributionListMember
from app.ticketing.models.interaction import Interaction
from app.ticketing.repositories.distribution_list_repository import (
    DistributionListRepository,
)
from app.ticketing.repositories.interaction_repository import InteractionRepository
from app.ticketing.repositories.mail_folder_repository import MailFolderRepository
from app.ticketing.repositories.rule_repository import RuleRepository
from app.ticketing.schemas.rule import RuleActionItem, RuleConditionGroup, RuleCreate, RuleUpdate
from app.ticketing.services.inbox_service import InboxService
from app.ticketing.services.mail_folder_service import MailFolderService
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


async def _get_distinct_active_agents(
    session, count: int, roles: list[str] | None = None
) -> list[User]:
    """
    `count` distinct active internal users eligible for Distribution
    List membership (any agent role, any category — membership
    eligibility doesn't care which, unless the caller narrows `roles`).
    Skips the test if the seeded dev DB doesn't have enough.

    `roles` defaults to every DL-eligible role including Site Lead. A
    caller that needs a genuinely *bounded* viewer (e.g. someone who
    must NOT see a communication outside their own scope) should pass
    a narrower list excluding Site Lead/Super Admin — under the
    communication-view RBAC fix, those two roles have no narrower
    business-defined scope anywhere in the system, so holding either
    communication:view_all or communication:view_assigned resolves to
    genuinely global visibility for them, same as it always has for
    view_all. A test asserting "this viewer sees nothing" should never
    draw a Site Lead/Super Admin as that viewer.
    """

    result = await session.execute(
        select(User)
        .options(joinedload(User.role), joinedload(User.category), joinedload(User.categories))
        .join(Role, Role.role_id == User.role_id)
        .where(
            Role.name.in_(roles or ["Team Lead", "Account Manager", "Staff", "Site Lead"]),
            User.is_active.is_(True),
        )
    )
    users = list(result.scalars().unique().all())
    if len(users) < count:
        pytest.skip(f"Need at least {count} distinct active agent users for this test.")
    return users[:count]


async def _make_client(session, *, account_manager_id) -> Client:
    client = Client(
        client_id=uuid.uuid4(),
        name="DL Sharing Test Client",
        inbox_email=f"dl-sharing-test-{uuid.uuid4().hex[:8]}@example.com",
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
            "client_name": "DL Sharing Test Client",
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


async def _make_distribution_list(session, *, created_by, member_ids, is_active=True) -> DistributionList:
    dl = DistributionList(
        distribution_list_id=uuid.uuid4(),
        name=f"DL Sharing Test List {uuid.uuid4().hex[:8]}",
        is_active=is_active,
        created_by=created_by,
    )
    session.add(dl)
    await session.flush()
    for user_id in member_ids:
        session.add(
            DistributionListMember(
                id=uuid.uuid4(), distribution_list_id=dl.distribution_list_id, user_id=user_id
            )
        )
    await session.flush()
    return dl


def _build_rule_service(session) -> RuleService:
    return RuleService(
        RuleRepository(session),
        MailFolderRepository(session),
        DistributionListRepository(session),
    )


async def _create_folder_rule(
    service,
    *,
    folder_name: str,
    current_user: User,
    shared_user_ids: list[uuid.UUID] | None = None,
    shared_distribution_list_ids: list[uuid.UUID] | None = None,
):
    request = RuleCreate(
        name=f"DL sharing test {uuid.uuid4().hex[:8]}",
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
        actions=[RuleActionItem.model_validate({"type": "move_to_folder", "folder_name": folder_name})],
        stop_processing=False,
        shared_user_ids=shared_user_ids or [],
        shared_distribution_list_ids=shared_distribution_list_ids or [],
    )
    return await service.create(request, current_user=current_user)


async def _resolve_access(session, folder, viewer) -> bool:
    mail_folder_service = MailFolderService(MailFolderRepository(session))
    access = await mail_folder_service.resolve_folder_access(
        folder, viewer, RuleRepository(session), DistributionListRepository(session)
    )
    return access.visible


async def test_distribution_list_member_gets_folder_and_inbox_access_non_member_denied(db_session):
    admin = await _get_super_admin(db_session)
    admin.permissions = ["rule:manage"]
    # Excludes Site Lead/Super Admin deliberately: under the
    # communication-view RBAC fix, those two roles have no narrower
    # business-defined scope, so either communication permission
    # resolves to genuine global visibility for them — `outsider` here
    # must be a role with an actual bounded scope (Team Lead/Staff's
    # own category, or Account Manager's own clients, none of which
    # include this test's admin-owned client/no-category item) so a
    # positive result can only come from the DL-sharing bypass itself.
    member_a, member_b, outsider = await _get_distinct_active_agents(
        db_session, 3, roles=["Team Lead", "Account Manager", "Staff"]
    )
    # communication:view_assigned alone is enough to reach
    # InboxService.get_inbox regardless of which of these three roles
    # the helper returns — granting communication:view_all here too
    # would (correctly, post-fix) grant genuine global visibility and
    # defeat this test's whole point (proving DL-sharing exclusivity,
    # not permission-driven global visibility).
    member_a.permissions = ["communication:view_assigned"]
    outsider.permissions = ["communication:view_assigned"]
    client = await _make_client(db_session, account_manager_id=admin.user_id)

    dl = await _make_distribution_list(
        db_session, created_by=admin.user_id, member_ids=[member_a.user_id, member_b.user_id]
    )

    service = _build_rule_service(db_session)
    folder_name = f"DL Sharing Test Folder {uuid.uuid4().hex[:8]}"
    await _create_folder_rule(
        service,
        folder_name=folder_name,
        current_user=admin,
        shared_distribution_list_ids=[dl.distribution_list_id],
    )

    folder_repository = MailFolderRepository(db_session)
    folder = await folder_repository.get_by_name(folder_name)
    assert folder is not None

    email = await _make_email(db_session, client_id=client.client_id, folder_id=folder.folder_id)

    # --- Folder-level access ---
    assert await _resolve_access(db_session, folder, member_a) is True
    assert await _resolve_access(db_session, folder, outsider) is False

    # --- Message-level (Inbox) access — the exact "folder visible but
    # 0 messages" bug class this whole feature exists to avoid. ---
    inbox_service = InboxService(InteractionRepository(db_session))
    member_result = await inbox_service.get_inbox(
        member_a, view="all", folder_id=folder.folder_id, bypass_ownership_scope=True
    )
    assert member_result.total == 1
    assert {item.interaction_id for item in member_result.items} == {email.interaction_id}

    outsider_result = await inbox_service.get_inbox(
        outsider, view="all", folder_id=folder.folder_id, bypass_ownership_scope=False
    )
    assert outsider_result.total == 0


async def test_distribution_list_membership_changes_take_effect_without_editing_rule(db_session):
    admin = await _get_super_admin(db_session)
    admin.permissions = ["rule:manage"]
    member_b, member_c = await _get_distinct_active_agents(db_session, 2)

    dl = await _make_distribution_list(db_session, created_by=admin.user_id, member_ids=[member_b.user_id])

    service = _build_rule_service(db_session)
    folder_name = f"DL Sharing Dynamic Folder {uuid.uuid4().hex[:8]}"
    await _create_folder_rule(
        service,
        folder_name=folder_name,
        current_user=admin,
        shared_distribution_list_ids=[dl.distribution_list_id],
    )
    folder = await MailFolderRepository(db_session).get_by_name(folder_name)

    # B starts as a member -> has access.
    assert await _resolve_access(db_session, folder, member_b) is True
    # C isn't a member yet -> no access.
    assert await _resolve_access(db_session, folder, member_c) is False

    # Remove B from the DL — no rule edit at all.
    dl_repository = DistributionListRepository(db_session)
    removed = await dl_repository.remove_member(dl.distribution_list_id, member_b.user_id)
    assert removed is True
    assert await _resolve_access(db_session, folder, member_b) is False

    # Add C to the DL — no rule edit at all.
    await dl_repository.add_member(dl.distribution_list_id, member_c.user_id)
    assert await _resolve_access(db_session, folder, member_c) is True


async def test_deactivating_distribution_list_revokes_access_dynamically(db_session):
    admin = await _get_super_admin(db_session)
    admin.permissions = ["rule:manage"]
    (member,) = await _get_distinct_active_agents(db_session, 1)

    dl = await _make_distribution_list(db_session, created_by=admin.user_id, member_ids=[member.user_id])

    service = _build_rule_service(db_session)
    folder_name = f"DL Sharing Deactivate Folder {uuid.uuid4().hex[:8]}"
    await _create_folder_rule(
        service,
        folder_name=folder_name,
        current_user=admin,
        shared_distribution_list_ids=[dl.distribution_list_id],
    )
    folder = await MailFolderRepository(db_session).get_by_name(folder_name)

    assert await _resolve_access(db_session, folder, member) is True

    dl.is_active = False
    await db_session.flush()

    assert await _resolve_access(db_session, folder, member) is False


async def test_mixed_employee_and_distribution_list_sharing(db_session):
    admin = await _get_super_admin(db_session)
    admin.permissions = ["rule:manage"]
    direct_employee, dl_only_member = await _get_distinct_active_agents(db_session, 2)

    dl = await _make_distribution_list(
        db_session, created_by=admin.user_id, member_ids=[dl_only_member.user_id]
    )

    service = _build_rule_service(db_session)
    folder_name = f"DL Sharing Mixed Folder {uuid.uuid4().hex[:8]}"
    rule = await _create_folder_rule(
        service,
        folder_name=folder_name,
        current_user=admin,
        shared_user_ids=[direct_employee.user_id],
        shared_distribution_list_ids=[dl.distribution_list_id],
    )
    folder = await MailFolderRepository(db_session).get_by_name(folder_name)

    # Both the direct share and the DL member get access.
    assert await _resolve_access(db_session, folder, direct_employee) is True
    assert await _resolve_access(db_session, folder, dl_only_member) is True

    # direct_employee is ALSO added to the DL — must still be exactly
    # one logical grant (no crash, no special-casing needed — the
    # check is a plain boolean OR).
    dl_repository = DistributionListRepository(db_session)
    await dl_repository.add_member(dl.distribution_list_id, direct_employee.user_id)
    assert await _resolve_access(db_session, folder, direct_employee) is True

    # Remove direct_employee from shared_user_ids (still a DL member)
    # -> access must survive via the DL grant alone.
    update_request = RuleUpdate(
        name=rule.name,
        is_enabled=rule.is_enabled,
        conditions=rule.conditions,
        exceptions=rule.exceptions,
        actions=rule.actions,
        stop_processing=rule.stop_processing,
        shared_user_ids=[],
        shared_distribution_list_ids=[dl.distribution_list_id],
    )
    await service.update(rule.rule_id, update_request, current_user=admin)
    assert await _resolve_access(db_session, folder, direct_employee) is True

    # Now also remove direct_employee from the DL -> no more grant at all.
    await dl_repository.remove_member(dl.distribution_list_id, direct_employee.user_id)
    assert await _resolve_access(db_session, folder, direct_employee) is False


async def test_rule_list_visibility_for_distribution_list_member(db_session):
    admin = await _get_super_admin(db_session)
    admin.permissions = ["rule:manage"]
    member, non_member = await _get_distinct_active_agents(db_session, 2)
    member.permissions = ["rule:manage"]
    non_member.permissions = ["rule:manage"]

    dl = await _make_distribution_list(db_session, created_by=admin.user_id, member_ids=[member.user_id])

    service = _build_rule_service(db_session)
    folder_name = f"DL Sharing Rule Visibility Folder {uuid.uuid4().hex[:8]}"
    rule = await _create_folder_rule(
        service,
        folder_name=folder_name,
        current_user=admin,
        shared_distribution_list_ids=[dl.distribution_list_id],
    )

    member_rules = await service.list_all(current_user=member)
    assert rule.rule_id in {r.rule_id for r in member_rules}

    non_member_rules = await service.list_all(current_user=non_member)
    assert rule.rule_id not in {r.rule_id for r in non_member_rules}

    # GET /rules/{id} directly, too.
    fetched = await service.get(rule.rule_id, current_user=member)
    assert fetched.rule_id == rule.rule_id
    with pytest.raises(HTTPException):
        await service.get(rule.rule_id, current_user=non_member)


async def test_create_rule_rejects_invalid_or_inactive_distribution_list_id(db_session):
    admin = await _get_super_admin(db_session)
    admin.permissions = ["rule:manage"]

    inactive_dl = await _make_distribution_list(
        db_session, created_by=admin.user_id, member_ids=[], is_active=False
    )

    service = _build_rule_service(db_session)

    with pytest.raises(HTTPException) as exc_info:
        await _create_folder_rule(
            service,
            folder_name=f"DL Sharing Invalid Folder {uuid.uuid4().hex[:8]}",
            current_user=admin,
            shared_distribution_list_ids=[uuid.uuid4()],
        )
    assert exc_info.value.status_code == 400

    with pytest.raises(HTTPException) as exc_info:
        await _create_folder_rule(
            service,
            folder_name=f"DL Sharing Inactive Folder {uuid.uuid4().hex[:8]}",
            current_user=admin,
            shared_distribution_list_ids=[inactive_dl.distribution_list_id],
        )
    assert exc_info.value.status_code == 400
