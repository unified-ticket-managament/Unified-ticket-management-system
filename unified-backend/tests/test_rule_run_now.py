"""
"Run rule now" — end-to-end against a real Postgres, through the real
RuleService (API layer), RBAC permission resolution, access-control
gates, worker and live engine.

The worker COMMITS (per email and per page, by design), so this module
only runs when explicitly pointed at a disposable database:

    UTMS_ALLOW_COMMITTING_DB_TESTS=1
    DATABASE_URL=postgresql://...  (migrated + scripts.rbac_seed.seed run)

It is skipped otherwise, so it can never write to a shared environment
by accident. Every test builds its own users/clients/rules with unique
names and a unique matching sender address, so tests never see each
other's data even though nothing is rolled back.
"""

import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from sqlalchemy import delete, func, select, text, update

pytestmark = pytest.mark.skipif(
    os.getenv("UTMS_ALLOW_COMMITTING_DB_TESTS") != "1",
    reason="Commits to the database — set UTMS_ALLOW_COMMITTING_DB_TESTS=1 against a disposable DB.",
)

from shared_models.models import Category, Role, User  # noqa: E402

from app.database.session import AsyncSessionLocal, engine  # noqa: E402
from app.notifications.models import Notification  # noqa: E402
from app.rbac.models.audit_log import AuditLog as RbacAuditLog  # noqa: E402
from app.rbac.models.reporting_manager_team import ReportingManagerTeam  # noqa: E402
from app.ticketing.enums import InteractionDirection, InteractionStatus  # noqa: E402
from app.ticketing.models.audit_log import AuditLog as TicketAuditLog  # noqa: E402
from app.ticketing.models.client import Client  # noqa: E402
from app.ticketing.models.interaction import Interaction  # noqa: E402
from app.ticketing.models.mail_folder import MailFolder  # noqa: E402
from app.ticketing.models.rule import Rule  # noqa: E402
from app.ticketing.models.rule_run import (  # noqa: E402
    RuleRun,
    RuleRunItem,
    RuleRunItemStatus,
    RuleRunStatus,
)
from app.ticketing.repositories.distribution_list_repository import (  # noqa: E402
    DistributionListRepository,
)
from app.ticketing.repositories.interaction_repository import InteractionRepository  # noqa: E402
from app.ticketing.repositories.mail_folder_repository import MailFolderRepository  # noqa: E402
from app.ticketing.repositories.rule_repository import RuleRepository  # noqa: E402
from app.ticketing.schemas.rule import RuleCreate, RuleUpdate  # noqa: E402
from app.ticketing.services import rule_run_worker  # noqa: E402
from app.ticketing.services.rule_conditions import RuleEmailContext  # noqa: E402
from app.ticketing.services.rule_engine_service import (  # noqa: E402
    RULE_FORWARD_LOCK_NAMESPACE,
    build_rule_engine_service,
)
from app.ticketing.services.rule_run_authorization import (  # noqa: E402
    RunScopeGate,
    load_authorized_user,
)
from app.ticketing.services.rule_service import RuleService  # noqa: E402


# ----------------------------------------------------------------------
# Fixtures / helpers
# ----------------------------------------------------------------------


class _RecordingMailProvider:
    def __init__(self, fail_for: set[str] | None = None):
        self.sent: list = []
        self.fail_for = fail_for or set()

    async def send_email(self, envelope):
        if envelope.to_email in self.fail_for:
            raise RuntimeError("simulated Graph send failure")
        self.sent.append(envelope)
        return None


@pytest.fixture
def mail(monkeypatch):
    provider = _RecordingMailProvider()
    monkeypatch.setattr(
        "app.ticketing.services.rule_engine_service.get_mail_provider_client",
        lambda settings: provider,
    )
    monkeypatch.setattr(
        "app.notifications.email_notifier.queue_notification_emails",
        lambda created: None,
    )
    return provider


@pytest.fixture(autouse=True)
async def _isolate_worker(monkeypatch):
    monkeypatch.setattr(rule_run_worker, "RECONCILE_GRACE", timedelta(0))
    rule_run_worker.reset_worker_state()
    # Nothing is rolled back between tests, so a run an earlier
    # (possibly failed) test left active would otherwise be claimed by
    # this test's drain() once its heartbeat went stale.
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(RuleRun)
            .where(RuleRun.status.in_(RuleRunStatus.ACTIVE))
            .values(status=RuleRunStatus.CANCELLED, status_reason="test_isolation")
        )
        await db.commit()
    yield
    rule_run_worker.reset_worker_state()
    await engine.dispose()


def _tag() -> str:
    return uuid.uuid4().hex[:10]


class World:
    """Satish/Ananya/Ravi (Account Managers), a Site Lead, a Team Lead,
    one client per AM, one category mailbox Satish reporting-manages, and
    a unique sender address this test's rules match on."""

    def __init__(self, tag: str):
        self.tag = tag
        self.sender = f"target-{tag}@example.com"
        self.users: dict[str, uuid.UUID] = {}
        self.clients: dict[str, uuid.UUID] = {}
        self.category_id: uuid.UUID | None = None


async def _role_id(db, name: str) -> uuid.UUID:
    return (await db.execute(select(Role.role_id).where(Role.name == name))).scalar_one()


async def build_world() -> World:
    world = World(_tag())
    async with AsyncSessionLocal() as db:
        for key, role in (
            ("satish", "Account Manager"),
            ("ananya", "Account Manager"),
            ("ravi", "Account Manager"),
            ("site_lead", "Site Lead"),
            ("team_lead", "Team Lead"),
            ("super_admin", "Super Admin"),
        ):
            user = User(
                name=f"{key}-{world.tag}",
                email=f"{key}-{world.tag}@probeps.com",
                password_hash="x",
                role_id=await _role_id(db, role),
                is_active=True,
            )
            db.add(user)
            await db.flush()
            world.users[key] = user.user_id

        for key in ("satish", "ananya", "ravi"):
            client = Client(
                name=f"client-{key}-{world.tag}",
                account_manager_id=world.users[key],
                is_active=True,
            )
            db.add(client)
            await db.flush()
            world.clients[key] = client.client_id

        category = Category(category_name=f"cat-{world.tag}")
        db.add(category)
        await db.flush()
        world.category_id = category.category_id
        db.add(
            ReportingManagerTeam(
                account_manager_id=world.users["satish"], category_id=category.category_id
            )
        )
        await db.commit()
    return world


async def principal(user_id: uuid.UUID, *, impersonator: tuple[uuid.UUID, str] | None = None) -> User:
    async with AsyncSessionLocal() as db:
        user = await load_authorized_user(db, user_id)
        assert user is not None
        if impersonator is not None:
            user.impersonator_id, user.impersonator_name = impersonator
        return user


async def add_email(
    world: World,
    *,
    sender: str | None = None,
    client: str | None = None,
    category: bool = False,
    parent_id: uuid.UUID | None = None,
    folder_id: uuid.UUID | None = None,
    payload_extra: dict | None = None,
    direction=InteractionDirection.INBOUND,
    interaction_type: str = "EMAIL",
    created_at: datetime | None = None,
    is_visible: bool = True,
    status=InteractionStatus.PENDING,
) -> uuid.UUID:
    async with AsyncSessionLocal() as db:
        payload = {
            "from_email": sender if sender is not None else world.sender,
            "subject": f"Subject {world.tag}",
            "body": "Body",
            "cc": [],
            **(payload_extra or {}),
        }
        interaction = Interaction(
            interaction_type=interaction_type,
            direction=direction,
            status=status,
            payload=payload,
            subject=payload.get("subject") if isinstance(payload.get("subject"), str) else None,
            message_id=f"<{uuid.uuid4().hex}@example.com>",
            is_visible=is_visible,
            client_id=world.clients[client] if client else None,
            category_id=world.category_id if category else None,
            parent_interaction_id=parent_id,
            folder_id=folder_id,
            received_at=datetime.now(timezone.utc),
        )
        if created_at is not None:
            interaction.created_at = created_at
        db.add(interaction)
        await db.commit()
        return interaction.interaction_id


def _rule_payload(world: World, actions: list[dict], *, run_now: bool, name: str | None = None, **extra):
    extra.setdefault("is_enabled", True)
    return dict(
        name=name or f"rule-{world.tag}",
        category="mail_rule",
        conditions={
            "combinator": "AND",
            "rules": [{"field": "sender_email", "operator": "equals", "value": world.sender}],
        },
        actions=actions,
        run_now=run_now,
        **extra,
    )


async def create_rule(world: World, owner: str, actions: list[dict], *, run_now: bool = True, **extra):
    user = await principal(world.users[owner], impersonator=extra.pop("impersonator", None))
    async with AsyncSessionLocal() as db:
        service = RuleService(
            RuleRepository(db), MailFolderRepository(db), DistributionListRepository(db), InteractionRepository(db)
        )
        response = await service.create(
            RuleCreate(**_rule_payload(world, actions, run_now=run_now, **extra)), current_user=user
        )
        await db.commit()
        return response


async def update_rule(world: World, rule_id: uuid.UUID, actor: str, actions: list[dict], *, run_now: bool, **extra):
    user = await principal(world.users[actor])
    payload = _rule_payload(world, actions, run_now=run_now, **extra)
    payload.pop("category")
    async with AsyncSessionLocal() as db:
        service = RuleService(
            RuleRepository(db), MailFolderRepository(db), DistributionListRepository(db), InteractionRepository(db)
        )
        response = await service.update(rule_id, RuleUpdate(**payload), current_user=user)
        await db.commit()
        return response


async def drain(max_ticks: int = 100) -> None:
    for _ in range(max_ticks):
        if await rule_run_worker.run_worker_tick(AsyncSessionLocal, budget_seconds=60) is None:
            return
    raise AssertionError("worker never went idle")


async def get_run(run_id) -> RuleRun:
    async with AsyncSessionLocal() as db:
        return (await db.execute(select(RuleRun).where(RuleRun.run_id == run_id))).scalar_one()


async def folder_of(interaction_id) -> uuid.UUID | None:
    async with AsyncSessionLocal() as db:
        return (
            await db.execute(select(Interaction.folder_id).where(Interaction.interaction_id == interaction_id))
        ).scalar_one()


async def folder_id_by_name(name: str) -> uuid.UUID | None:
    async with AsyncSessionLocal() as db:
        return (await db.execute(select(MailFolder.folder_id).where(MailFolder.name == name))).scalar_one_or_none()


def move(name: str) -> dict:
    return {"type": "move_to_folder", "folder_name": name}


def forward(*user_ids) -> dict:
    return {"type": "forward_to", "employee_user_ids": [str(u) for u in user_ids]}


# ----------------------------------------------------------------------
# Basic
# ----------------------------------------------------------------------


async def test_rule_without_run_now_queues_nothing_and_leaves_history_alone(mail):
    world = await build_world()
    s1 = await add_email(world, client="satish")
    rule = await create_rule(world, "satish", [move(f"F-{world.tag}")], run_now=False)

    assert rule.active_run is None
    async with AsyncSessionLocal() as db:
        count = (await db.execute(select(func.count()).select_from(RuleRun).where(RuleRun.rule_id == rule.rule_id))).scalar_one()
    assert count == 0
    await drain()
    assert await folder_of(s1) is None


async def test_rule_with_run_now_queues_exactly_one_run_and_audits_request(mail):
    world = await build_world()
    rule = await create_rule(world, "satish", [move(f"F-{world.tag}")])

    assert rule.active_run is not None and rule.active_run.status == RuleRunStatus.QUEUED
    async with AsyncSessionLocal() as db:
        runs = (await db.execute(select(RuleRun).where(RuleRun.rule_id == rule.rule_id))).scalars().all()
        assert len(runs) == 1
        assert runs[0].triggered_by == world.users["satish"]
        assert runs[0].rule_owner_id == world.users["satish"]
        requested = (
            await db.execute(
                select(RbacAuditLog).where(
                    RbacAuditLog.entity_id == str(rule.rule_id),
                    RbacAuditLog.action == "rule.run_now.requested",
                )
            )
        ).scalars().all()
        assert len(requested) == 1


async def test_future_email_still_processed_by_live_engine_after_run(mail):
    world = await build_world()
    folder = f"F-{world.tag}"
    rule = await create_rule(world, "satish", [move(folder)])
    await drain()
    assert (await get_run(rule.active_run.run_id)).status == RuleRunStatus.COMPLETED

    future = await add_email(world, client="satish")
    async with AsyncSessionLocal() as db:
        interaction = await db.get(Interaction, future)
        await build_rule_engine_service(db).evaluate_and_execute_for_email(
            interaction=interaction,
            context=RuleEmailContext(from_email=world.sender, subject="s", body="b", client_id=world.clients["satish"]),
        )
        await db.commit()
    assert await folder_of(future) == await folder_id_by_name(folder)


# ----------------------------------------------------------------------
# Cross-user isolation (the most important test)
# ----------------------------------------------------------------------


async def test_cross_user_isolation_matrix(mail):
    world = await build_world()
    other = f"other-{world.tag}@example.com"
    s1 = await add_email(world, client="satish")
    s2 = await add_email(world, client="satish", sender=other)
    a1 = await add_email(world, client="ananya")
    a2 = await add_email(world, client="ananya", sender=other)
    r1 = await add_email(world, client="ravi")
    r2 = await add_email(world, client="ravi", sender=other)
    x1 = await add_email(world)  # shared Graph mailbox, no client/category
    x2 = await add_email(world, sender=other)
    c1 = await add_email(world, category=True)  # Satish is its Reporting Manager
    c2 = await add_email(world, category=True, sender=other)

    folder = f"X-{world.tag}"
    rule = await create_rule(world, "satish", [move(folder)])
    await drain()

    target = await folder_id_by_name(folder)
    assert await folder_of(s1) == target
    assert await folder_of(c1) == target
    for unchanged in (s2, a1, a2, r1, r2, x1, x2, c2):
        assert await folder_of(unchanged) is None, unchanged

    run = await get_run(rule.active_run.run_id)
    assert run.status == RuleRunStatus.COMPLETED
    # a1/r1/x1 match the condition but are outside Satish's scope. The
    # prefilter keeps most of them out of the scan entirely; any that
    # reach the gate are skipped out_of_scope, never moved.
    assert run.succeeded_count == 2
    assert run.failed_count == 0


async def test_site_lead_triggering_owner_rule_does_not_expand_scope(mail):
    world = await build_world()
    s1 = await add_email(world, client="satish")
    a1 = await add_email(world, client="ananya")
    x1 = await add_email(world)
    folder = f"SL-{world.tag}"
    rule = await create_rule(world, "satish", [move(folder)], run_now=False)

    # Site Lead holds rule:manage_all (can manage Satish's rule) and a
    # global inbox — but the run is Satish ∩ Site Lead = Satish.
    response = await update_rule(world, rule.rule_id, "site_lead", [move(folder)], run_now=True)
    await drain()

    target = await folder_id_by_name(folder)
    assert await folder_of(s1) == target
    assert await folder_of(a1) is None
    assert await folder_of(x1) is None
    run = await get_run(response.active_run.run_id)
    assert run.triggered_by == world.users["site_lead"]
    assert run.rule_owner_id == world.users["satish"]


async def test_shared_rule_run_by_another_manager_is_the_intersection(mail):
    world = await build_world()
    s1 = await add_email(world, client="satish")
    a1 = await add_email(world, client="ananya")
    c1 = await add_email(world, category=True)
    # Ananya is ALSO a Reporting Manager of the category — the only mail
    # both she and Satish may act on.
    async with AsyncSessionLocal() as db:
        db.add(ReportingManagerTeam(account_manager_id=world.users["ananya"], category_id=world.category_id))
        await db.commit()

    rule = await create_rule(
        world, "satish", [forward(world.users["ravi"])], run_now=False,
        shared_user_ids=[world.users["ananya"]],
    )
    response = await update_rule(
        world, rule.rule_id, "ananya", [forward(world.users["ravi"])], run_now=True,
        shared_user_ids=[world.users["ananya"]],
    )
    await drain()

    run = await get_run(response.active_run.run_id)
    assert run.status == RuleRunStatus.COMPLETED
    assert run.triggered_by == world.users["ananya"]
    async with AsyncSessionLocal() as db:
        forwarded = (
            await db.execute(
                select(RuleRunItem.interaction_id).where(
                    RuleRunItem.run_id == run.run_id, RuleRunItem.status == RuleRunItemStatus.SENT
                )
            )
        ).scalars().all()
    # Satish ∩ Ananya = the shared category mail only.
    assert forwarded == [c1]
    assert len(mail.sent) == 1
    assert s1 and a1


async def test_shared_user_cannot_use_rule_owners_private_folder(mail):
    world = await build_world()
    c1 = await add_email(world, category=True)
    async with AsyncSessionLocal() as db:
        db.add(ReportingManagerTeam(account_manager_id=world.users["ananya"], category_id=world.category_id))
        await db.commit()
    folder = f"OWN-{world.tag}"
    # Saved by Satish -> the folder is created as Satish's.
    rule = await create_rule(
        world, "satish", [move(folder)], run_now=False, shared_user_ids=[world.users["ananya"]]
    )
    response = await update_rule(
        world, rule.rule_id, "ananya", [move(folder)], run_now=True, shared_user_ids=[world.users["ananya"]]
    )
    await drain()

    # Ananya only "sees" Satish's folder through this rule's own sharing
    # — which can't authorize itself — so the move is skipped.
    assert await folder_of(c1) is None
    run = await get_run(response.active_run.run_id)
    assert run.skipped_by_reason.get("folder_unauthorized", 0) >= 1


# ----------------------------------------------------------------------
# Folder security
# ----------------------------------------------------------------------


async def test_rule_cannot_take_over_another_users_private_folder(mail):
    world = await build_world()
    s1 = await add_email(world, client="satish")
    private = f"Ananya-Private-{world.tag}"
    async with AsyncSessionLocal() as db:
        db.add(MailFolder(name=private, created_by=world.users["ananya"], is_rule_created=False))
        await db.commit()

    rule = await create_rule(world, "satish", [move(private)])
    await drain()

    assert await folder_of(s1) is None
    run = await get_run(rule.active_run.run_id)
    assert run.skipped_by_reason.get("folder_unauthorized") == 1
    async with AsyncSessionLocal() as db:
        item = (
            await db.execute(select(RuleRunItem).where(RuleRunItem.run_id == run.run_id))
        ).scalar_one()
        assert item.status == RuleRunItemStatus.SKIPPED
        assert item.skip_reason == "folder_unauthorized"


async def test_rule_folder_and_rule_sharing_never_grant_mail_action_access(mail):
    world = await build_world()
    s1 = await add_email(world, client="satish")
    folder = f"G-{world.tag}"
    await create_rule(world, "satish", [move(folder)], shared_user_ids=[world.users["ananya"]])
    await drain()
    assert await folder_of(s1) == await folder_id_by_name(folder)

    # Ananya is shared on the rule AND s1 now sits in that rule's folder
    # — yet the run-now gate still refuses her for it.
    ananya = await principal(world.users["ananya"])
    satish = await principal(world.users["satish"])
    async with AsyncSessionLocal() as db:
        root = await db.get(Interaction, s1)
        gate = RunScopeGate(owner=satish, trigger=ananya, db=db)
        assert await gate.allows(action_type="move_to_folder", root=root) is False
        assert await gate.allows(action_type="forward_to", root=root) is False
        own = RunScopeGate(owner=satish, trigger=satish, db=db)
        assert await own.allows(action_type="move_to_folder", root=root) is True


# ----------------------------------------------------------------------
# Move semantics
# ----------------------------------------------------------------------


async def test_move_already_in_target_other_folder_and_unfiled(mail):
    world = await build_world()
    folder = f"M-{world.tag}"
    elsewhere = f"Manual-{world.tag}"
    async with AsyncSessionLocal() as db:
        target = MailFolder(name=folder, created_by=world.users["satish"], is_rule_created=True)
        other = MailFolder(name=elsewhere, created_by=world.users["satish"], is_rule_created=False)
        db.add_all([target, other])
        await db.commit()
        target_id, other_id = target.folder_id, other.folder_id

    in_target = await add_email(world, client="satish", folder_id=target_id)
    in_other = await add_email(world, client="satish", folder_id=other_id)
    unfiled = await add_email(world, client="satish")

    rule = await create_rule(world, "satish", [move(folder)])
    await drain()

    assert await folder_of(in_target) == target_id
    assert await folder_of(in_other) == other_id  # human filing preserved
    assert await folder_of(unfiled) == target_id

    run = await get_run(rule.active_run.run_id)
    assert run.already_applied_count == 1
    assert run.succeeded_count == 1
    assert run.skipped_by_reason.get("already_filed") == 1

    async with AsyncSessionLocal() as db:
        audits = (
            await db.execute(select(TicketAuditLog).where(TicketAuditLog.entity_id.in_([in_target, in_other, unfiled])))
        ).scalars().all()
        # Only the genuinely moved email gets a folder-change audit row,
        # and it carries the run's provenance.
        assert [a.entity_id for a in audits] == [unfiled]
        assert audits[0].new_values["source"] == "run_now"
        assert audits[0].new_values["run_id"] == str(run.run_id)


async def test_concurrent_manual_move_wins_over_conditional_file(mail):
    world = await build_world()
    email_id = await add_email(world, client="satish")
    async with AsyncSessionLocal() as db:
        a = MailFolder(name=f"A-{world.tag}", created_by=world.users["satish"])
        b = MailFolder(name=f"B-{world.tag}", created_by=world.users["satish"])
        db.add_all([a, b])
        await db.commit()
        a_id, b_id = a.folder_id, b.folder_id

    async with AsyncSessionLocal() as worker_db:
        stale = await worker_db.get(Interaction, email_id)  # loaded while unfiled
        async with AsyncSessionLocal() as human_db:
            await human_db.execute(update(Interaction).where(Interaction.interaction_id == email_id).values(folder_id=a_id))
            await human_db.commit()
        filed = await InteractionRepository(worker_db).set_folder_if_unfiled(stale, b_id)
        await worker_db.commit()
        assert filed is False
        assert stale.folder_id == a_id
    assert await folder_of(email_id) == a_id


# ----------------------------------------------------------------------
# create_folder
# ----------------------------------------------------------------------


async def test_create_folder_action_creates_once_and_respects_foreign_folders(mail):
    world = await build_world()
    await add_email(world, client="satish")
    mine = f"CF-{world.tag}"
    rule = await create_rule(world, "satish", [{"type": "create_folder", "folder_name": mine}])
    await drain()
    async with AsyncSessionLocal() as db:
        count = (await db.execute(select(func.count()).select_from(MailFolder).where(MailFolder.name == mine))).scalar_one()
    assert count == 1
    assert (await get_run(rule.active_run.run_id)).status == RuleRunStatus.COMPLETED


# ----------------------------------------------------------------------
# Forward
# ----------------------------------------------------------------------


async def test_forward_sends_once_and_rerun_does_not_duplicate(mail):
    world = await build_world()
    s1 = await add_email(world, client="satish")
    a1 = await add_email(world, client="ananya")
    recipient = world.users["ravi"]

    rule = await create_rule(world, "satish", [forward(recipient, recipient)])  # duplicate recipient
    await drain()
    assert len(mail.sent) == 1
    run1 = await get_run(rule.active_run.run_id)
    assert run1.forwards_sent_count == 1

    # Explicit second run of the same rule.
    second = await update_rule(world, rule.rule_id, "satish", [forward(recipient)], run_now=True)
    assert second.active_run.run_id != run1.run_id
    await drain()
    assert len(mail.sent) == 1  # no duplicate external email
    run2 = await get_run(second.active_run.run_id)
    assert run2.already_applied_count == 1
    assert run2.forwards_sent_count == 0

    async with AsyncSessionLocal() as db:
        notes = (
            await db.execute(select(Notification).where(Notification.related_entity_id.in_([s1, a1])))
        ).scalars().all()
        assert [n.related_entity_id for n in notes] == [s1]


async def test_forward_multiple_recipients_and_partial_failure(mail):
    world = await build_world()
    await add_email(world, client="satish")
    rule = await create_rule(world, "satish", [forward(world.users["ravi"], world.users["ananya"])])
    mail.fail_for = {f"ananya-{world.tag}@probeps.com"}
    await drain()
    assert [e.to_email for e in mail.sent] == [f"ravi-{world.tag}@probeps.com"]
    async with AsyncSessionLocal() as db:
        item = (await db.execute(select(RuleRunItem).where(RuleRunItem.run_id == rule.active_run.run_id))).scalar_one()
    assert item.status == RuleRunItemStatus.SENT
    assert item.result["failed_user_ids"] == [str(world.users["ananya"])]


async def test_forward_send_failure_is_recorded_not_fatal(mail):
    world = await build_world()
    await add_email(world, client="satish")
    second = await add_email(world, client="satish")
    rule = await create_rule(world, "satish", [forward(world.users["ravi"])])
    mail.fail_for = {f"ravi-{world.tag}@probeps.com"}
    await drain()
    run = await get_run(rule.active_run.run_id)
    assert run.status == RuleRunStatus.COMPLETED
    assert run.failed_count == 2
    assert second  # both attempted, neither aborted the run


async def test_crash_after_send_marks_unknown_and_never_resends(mail, monkeypatch):
    world = await build_world()
    s1 = await add_email(world, client="satish")

    async def _explode(*args, **kwargs):
        raise RuntimeError("DB write after send failed")

    monkeypatch.setattr("app.notifications.service.NotificationService.notify", _explode)
    rule = await create_rule(world, "satish", [forward(world.users["ravi"])])
    await drain()
    assert len(mail.sent) == 1
    async with AsyncSessionLocal() as db:
        item = (await db.execute(select(RuleRunItem).where(RuleRunItem.run_id == rule.active_run.run_id))).scalar_one()
    assert item.status == RuleRunItemStatus.UNKNOWN

    monkeypatch.undo()
    monkeypatch.setattr(rule_run_worker, "RECONCILE_GRACE", timedelta(0))
    monkeypatch.setattr(
        "app.ticketing.services.rule_engine_service.get_mail_provider_client", lambda settings: mail
    )
    monkeypatch.setattr("app.notifications.email_notifier.queue_notification_emails", lambda created: None)
    second = await update_rule(world, rule.rule_id, "satish", [forward(world.users["ravi"])], run_now=True)
    await drain()
    assert len(mail.sent) == 1  # never re-sent
    run2 = await get_run(second.active_run.run_id)
    assert run2.skipped_by_reason.get("prior_send_state_unknown") == 1
    assert s1


async def test_sending_item_found_on_resume_becomes_unknown(mail):
    world = await build_world()
    s1 = await add_email(world, client="satish")
    rule = await create_rule(world, "satish", [forward(world.users["ravi"])])
    run_id = rule.active_run.run_id
    # Simulate a worker that committed SENDING, sent, then died.
    async with AsyncSessionLocal() as db:
        db.add(
            RuleRunItem(
                run_id=run_id, interaction_id=s1, rule_id=rule.rule_id,
                action_index=0, action_type="forward_to", status=RuleRunItemStatus.SENDING,
            )
        )
        await db.commit()
    await drain()
    assert mail.sent == []
    async with AsyncSessionLocal() as db:
        item = (await db.execute(select(RuleRunItem).where(RuleRunItem.run_id == run_id))).scalar_one()
    assert item.status == RuleRunItemStatus.UNKNOWN


async def test_forward_cap_stops_run_as_capped(mail, monkeypatch):
    monkeypatch.setattr(rule_run_worker, "HISTORICAL_FORWARD_CAP", 2)
    world = await build_world()
    for _ in range(4):
        await add_email(world, client="satish")
    rule = await create_rule(world, "satish", [forward(world.users["ravi"])])
    await drain()
    run = await get_run(rule.active_run.run_id)
    assert run.status == RuleRunStatus.CAPPED
    assert run.forwards_sent_count == 2
    assert len(mail.sent) == 2
    assert "safety limit" in (run.status_reason or "")


async def test_live_engine_forward_lock_excludes_concurrent_run_now_forward(mail):
    world = await build_world()
    s1 = await add_email(world, client="satish")
    key = {"ns": RULE_FORWARD_LOCK_NAMESPACE, "key": str(s1)}
    async with engine.connect() as holder:
        # What the worker holds around a run-now forward.
        await holder.execute(text("SELECT pg_advisory_lock(:ns, hashtext(:key))"), key)
        await holder.commit()
        try:
            async with AsyncSessionLocal() as live_db:
                await live_db.execute(text("SET LOCAL lock_timeout = '300ms'"))
                service = build_rule_engine_service(live_db)
                with pytest.raises(Exception) as excinfo:
                    await service._lock_interaction_for_forward(s1)
                assert "lock" in str(excinfo.value).lower()
                await live_db.rollback()
        finally:
            await holder.execute(text("SELECT pg_advisory_unlock(:ns, hashtext(:key))"), key)
            await holder.commit()


# ----------------------------------------------------------------------
# Multiple actions, threads, eligibility
# ----------------------------------------------------------------------


async def test_multiple_actions_on_same_email(mail):
    world = await build_world()
    s1 = await add_email(world, client="satish")
    folder = f"MA-{world.tag}"
    rule = await create_rule(world, "satish", [move(folder), forward(world.users["ravi"])])
    await drain()
    assert await folder_of(s1) == await folder_id_by_name(folder)
    assert len(mail.sent) == 1
    async with AsyncSessionLocal() as db:
        items = (await db.execute(select(RuleRunItem).where(RuleRunItem.run_id == rule.active_run.run_id).order_by(RuleRunItem.action_index))).scalars().all()
    assert [(i.action_type, i.status) for i in items] == [
        ("move_to_folder", RuleRunItemStatus.APPLIED),
        ("forward_to", RuleRunItemStatus.SENT),
    ]


async def test_thread_semantics_are_per_interaction(mail):
    world = await build_world()
    other = f"other-{world.tag}@example.com"
    root_no_match = await add_email(world, client="satish", sender=other)
    reply_match = await add_email(world, parent_id=root_no_match)  # reply's own client unresolved
    root_match = await add_email(world, client="satish")
    reply_no_match = await add_email(world, parent_id=root_match, sender=other)
    outbound = await add_email(world, client="satish", direction=InteractionDirection.OUTBOUND)
    forward_row = await add_email(world, client="satish", interaction_type="FORWARD", direction=InteractionDirection.OUTBOUND)
    hidden = await add_email(world, client="satish", is_visible=False)
    foreign_reply = await add_email(world, parent_id=await add_email(world, client="ananya", sender=other))

    folder = f"T-{world.tag}"
    await create_rule(world, "satish", [move(folder)])
    await drain()
    target = await folder_id_by_name(folder)

    assert await folder_of(reply_match) == target  # authorized via its root
    assert await folder_of(root_no_match) is None  # no thread-wide spread
    assert await folder_of(root_match) == target
    assert await folder_of(reply_no_match) is None
    for excluded in (outbound, forward_row, hidden, foreign_reply):
        assert await folder_of(excluded) is None


async def test_archived_and_ticket_status_mail_is_eligible(mail):
    world = await build_world()
    archived = await add_email(world, client="satish", status=InteractionStatus.IGNORED)
    folder = f"AR-{world.tag}"
    await create_rule(world, "satish", [move(folder)])
    await drain()
    assert await folder_of(archived) == await folder_id_by_name(folder)


async def test_higher_priority_stop_processing_rule_suppresses_target(mail):
    world = await build_world()
    s1 = await add_email(world, client="satish")
    # An earlier, enabled rule that matches the same mail and stops
    # processing (its own action never runs during the run).
    await create_rule(
        world, "ananya", [move(f"Stopper-{world.tag}")], run_now=False,
        name=f"stopper-{world.tag}", stop_processing=True,
    )
    rule = await create_rule(world, "satish", [move(f"After-{world.tag}")])
    await drain()
    assert await folder_of(s1) is None
    run = await get_run(rule.active_run.run_id)
    assert run.skipped_by_reason.get("stopped_by_higher_priority_rule") == 1


# ----------------------------------------------------------------------
# Pagination
# ----------------------------------------------------------------------


@pytest.mark.parametrize("count", [0, 1, 3, 4, 7])
async def test_pagination_processes_every_row_exactly_once(mail, monkeypatch, count):
    monkeypatch.setattr(rule_run_worker, "PAGE_SIZE", 3)  # 3 = exactly a page, 4 = page+1
    world = await build_world()
    same_instant = datetime.now(timezone.utc) - timedelta(minutes=1)
    ids = [
        # Several rows share one created_at — the interaction_id
        # tie-break must still visit each exactly once.
        await add_email(world, client="satish", created_at=same_instant if i % 2 == 0 else None)
        for i in range(count)
    ]
    folder = f"P-{world.tag}-{count}"
    rule = await create_rule(world, "satish", [move(folder)])
    await drain()
    run = await get_run(rule.active_run.run_id)
    assert run.status == RuleRunStatus.COMPLETED
    assert run.succeeded_count == count
    async with AsyncSessionLocal() as db:
        items = (await db.execute(select(RuleRunItem.interaction_id).where(RuleRunItem.run_id == run.run_id))).scalars().all()
    assert sorted(items) == sorted(ids)
    if count:
        target = await folder_id_by_name(folder)
        for i in ids:
            assert await folder_of(i) == target


async def test_large_mailbox_with_match_on_last_page(mail, monkeypatch):
    monkeypatch.setattr(rule_run_worker, "PAGE_SIZE", 50)
    world = await build_world()
    other = f"other-{world.tag}@example.com"
    async with AsyncSessionLocal() as db:
        base = datetime.now(timezone.utc) - timedelta(hours=1)
        for i in range(1000):
            db.add(
                Interaction(
                    interaction_type="EMAIL", direction=InteractionDirection.INBOUND,
                    status=InteractionStatus.PENDING,
                    payload={"from_email": other, "subject": "bulk", "body": "x" * 200},
                    message_id=f"<{uuid.uuid4().hex}@example.com>", is_visible=True,
                    client_id=world.clients["satish"], created_at=base + timedelta(seconds=i),
                )
            )
        await db.commit()
    last = await add_email(world, client="satish")
    folder = f"L-{world.tag}"
    rule = await create_rule(world, "satish", [move(folder)])
    await drain()
    run = await get_run(rule.active_run.run_id)
    assert run.scanned_count >= 1001
    assert run.succeeded_count == 1
    assert await folder_of(last) == await folder_id_by_name(folder)


# ----------------------------------------------------------------------
# Failure isolation, restart, concurrency
# ----------------------------------------------------------------------


async def test_one_bad_email_does_not_stop_the_run(mail, monkeypatch):
    world = await build_world()
    good1 = await add_email(world, client="satish")
    bad = await add_email(world, client="satish", payload_extra={"cc": "not-a-list", "subject": {"weird": True}})
    good2 = await add_email(world, client="satish")
    boom = await add_email(world, client="satish")

    original = rule_run_worker.RuleRunProcessor._run_move

    async def _flaky(self, index, action, interaction):
        if interaction.interaction_id == boom:
            raise ValueError("simulated malformed interaction")
        return await original(self, index, action, interaction)

    monkeypatch.setattr(rule_run_worker.RuleRunProcessor, "_run_move", _flaky)
    folder = f"B-{world.tag}"
    rule = await create_rule(world, "satish", [move(folder)])
    await drain()
    target = await folder_id_by_name(folder)
    assert await folder_of(good1) == target
    assert await folder_of(good2) == target
    assert await folder_of(boom) is None
    run = await get_run(rule.active_run.run_id)
    assert run.status == RuleRunStatus.COMPLETED
    assert run.failed_count == 1
    assert any(e["interaction_id"] == str(boom) for e in run.error_samples)
    assert bad  # malformed payload evaluated safely (no match on dict subject)


async def test_double_submit_returns_existing_active_run(mail):
    world = await build_world()
    rule = await create_rule(world, "satish", [move(f"D-{world.tag}")])
    again = await update_rule(world, rule.rule_id, "satish", [move(f"D-{world.tag}")], run_now=True)
    assert again.active_run.run_id == rule.active_run.run_id

    # The database itself refuses a second active run.
    async with AsyncSessionLocal() as db:
        db.add(
            RuleRun(
                rule_id=rule.rule_id, rule_name="dup", triggered_by=world.users["satish"],
                status=RuleRunStatus.QUEUED, rule_snapshot={}, cutoff_at=datetime.now(timezone.utc),
            )
        )
        with pytest.raises(Exception):
            await db.commit()


async def test_worker_restart_resumes_from_cursor_without_duplicates(mail, monkeypatch):
    monkeypatch.setattr(rule_run_worker, "PAGE_SIZE", 2)
    world = await build_world()
    ids = [await add_email(world, client="satish") for _ in range(5)]
    rule = await create_rule(world, "satish", [move(f"R-{world.tag}"), forward(world.users["ravi"])])

    # One page, then "crash": the tick's budget runs out immediately.
    async with AsyncSessionLocal() as db:
        run = await rule_run_worker.claim_next_run(db)
        processor = rule_run_worker.RuleRunProcessor(db, run)
        import time as _time
        await processor._step()  # revalidate + first page
        await processor.process(deadline=_time.monotonic() - 1)
    # Process restarts: forget in-memory state, make the heartbeat stale.
    rule_run_worker.reset_worker_state()
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(RuleRun).where(RuleRun.run_id == rule.active_run.run_id)
            .values(heartbeat_at=datetime.now(timezone.utc) - timedelta(hours=1))
        )
        await db.commit()
    await drain()

    run = await get_run(rule.active_run.run_id)
    assert run.status == RuleRunStatus.COMPLETED
    assert run.succeeded_count == 5
    assert len(mail.sent) == 5  # each email forwarded exactly once
    async with AsyncSessionLocal() as db:
        items = (await db.execute(select(func.count()).select_from(RuleRunItem).where(RuleRunItem.run_id == run.run_id))).scalar_one()
    assert items == 10
    assert ids


async def test_infrastructure_failure_resumes_from_saved_cursor(mail, monkeypatch):
    world = await build_world()
    s1 = await add_email(world, client="satish")
    rule = await create_rule(world, "satish", [move(f"I-{world.tag}")])
    calls = {"n": 0}
    original = rule_run_worker.RuleRunProcessor._fetch_page

    async def _flaky_fetch(self, page, *, lower_bound):
        calls["n"] += 1
        if calls["n"] == 1:
            from sqlalchemy.exc import OperationalError
            raise OperationalError("SELECT", {}, Exception("connection reset"))
        return await original(self, page, lower_bound=lower_bound)

    monkeypatch.setattr(rule_run_worker.RuleRunProcessor, "_fetch_page", _flaky_fetch)
    await drain()
    run = await get_run(rule.active_run.run_id)
    assert run.status == RuleRunStatus.COMPLETED
    assert run.attempts == 1
    assert await folder_of(s1) == await folder_id_by_name(f"I-{world.tag}")


# ----------------------------------------------------------------------
# Snapshot, cancellation, RBAC
# ----------------------------------------------------------------------


async def test_edit_after_trigger_does_not_change_the_run(mail):
    world = await build_world()
    s1 = await add_email(world, client="satish")
    folder = f"SN-{world.tag}"
    rule = await create_rule(world, "satish", [move(folder)])
    # Edited before the worker picks it up: different sender, different folder.
    async with AsyncSessionLocal() as db:
        row = await db.get(Rule, rule.rule_id)
        row.conditions = {"combinator": "AND", "rules": [{"field": "sender_email", "operator": "equals", "value": "nobody@example.com"}]}
        row.actions = [move(f"Other-{world.tag}")]
        row.priority = 999
        await db.commit()
    await drain()
    assert await folder_of(s1) == await folder_id_by_name(folder)


@pytest.mark.parametrize("change, reason", [("disable", "rule_disabled"), ("delete", "rule_deleted")])
async def test_disable_or_delete_cancels_and_preserves_run(mail, change, reason):
    world = await build_world()
    s1 = await add_email(world, client="satish")
    rule = await create_rule(world, "satish", [move(f"C-{world.tag}")])
    async with AsyncSessionLocal() as db:
        if change == "disable":
            await db.execute(update(Rule).where(Rule.rule_id == rule.rule_id).values(is_enabled=False))
        else:
            await db.execute(delete(Rule).where(Rule.rule_id == rule.rule_id))
        await db.commit()
    await drain()
    run = await get_run(rule.active_run.run_id)
    assert run.status == RuleRunStatus.CANCELLED
    assert run.status_reason == reason
    assert await folder_of(s1) is None
    if change == "delete":
        assert run.rule_id is None and run.rule_name == f"rule-{world.tag}"


async def test_cannot_trigger_run_on_rule_you_cannot_manage(mail):
    world = await build_world()
    rule = await create_rule(world, "satish", [move(f"N-{world.tag}")], run_now=False)
    with pytest.raises(HTTPException) as excinfo:
        await update_rule(world, rule.rule_id, "ananya", [move(f"N-{world.tag}")], run_now=True)
    assert excinfo.value.status_code == 403


async def test_team_lead_without_move_permission_cannot_run_move_rule(mail):
    world = await build_world()
    with pytest.raises(HTTPException) as excinfo:
        await create_rule(world, "team_lead", [move(f"TL-{world.tag}")])
    assert excinfo.value.status_code == 403


async def test_disabled_rule_cannot_run_now(mail):
    world = await build_world()
    with pytest.raises(HTTPException) as excinfo:
        await create_rule(world, "satish", [move(f"DIS-{world.tag}")], is_enabled=False)
    assert excinfo.value.status_code == 422


async def test_inactive_owner_cancels_run(mail):
    world = await build_world()
    await add_email(world, client="satish")
    rule = await create_rule(world, "satish", [move(f"IO-{world.tag}")])
    async with AsyncSessionLocal() as db:
        await db.execute(update(User).where(User.user_id == world.users["satish"]).values(is_active=False))
        await db.commit()
    await drain()
    run = await get_run(rule.active_run.run_id)
    assert run.status == RuleRunStatus.CANCELLED
    assert run.status_reason == "rule_owner_inactive"


async def test_unsharing_mid_run_cancels_the_shared_users_run(mail, monkeypatch):
    monkeypatch.setattr(rule_run_worker, "PAGE_SIZE", 1)
    world = await build_world()
    async with AsyncSessionLocal() as db:
        db.add(ReportingManagerTeam(account_manager_id=world.users["ananya"], category_id=world.category_id))
        await db.commit()
    for _ in range(3):
        await add_email(world, category=True)
    rule = await create_rule(world, "satish", [forward(world.users["ravi"])], run_now=False, shared_user_ids=[world.users["ananya"]])
    response = await update_rule(world, rule.rule_id, "ananya", [forward(world.users["ravi"])], run_now=True, shared_user_ids=[world.users["ananya"]])

    monkeypatch.setattr(rule_run_worker, "REVALIDATE_INTERVAL_SECONDS", 0.0)
    async with AsyncSessionLocal() as db:
        run = await rule_run_worker.claim_next_run(db)
        processor = rule_run_worker.RuleRunProcessor(db, run)
        await processor._step()  # first page under valid authorization
        async with AsyncSessionLocal() as admin_db:
            await admin_db.execute(update(Rule).where(Rule.rule_id == rule.rule_id).values(shared_user_ids=[]))
            await admin_db.commit()
        # The SAME in-flight processor notices on its next check.
        import time as _time
        assert await processor.process(deadline=_time.monotonic() + 30) == "finished"
    run = await get_run(response.active_run.run_id)
    assert run.status == RuleRunStatus.CANCELLED
    assert run.status_reason == "triggering_user_unauthorized"
    assert len(mail.sent) == 1


async def test_impersonated_trigger_uses_target_scope_and_records_admin(mail):
    world = await build_world()
    s1 = await add_email(world, client="satish")
    a1 = await add_email(world, client="ananya")
    admin_id = world.users["super_admin"]
    folder = f"IMP-{world.tag}"
    rule = await create_rule(world, "satish", [move(folder)], impersonator=(admin_id, "Admin"))
    await drain()

    run = await get_run(rule.active_run.run_id)
    assert run.triggered_by == world.users["satish"]
    assert run.impersonator_id == admin_id
    assert await folder_of(s1) == await folder_id_by_name(folder)
    assert await folder_of(a1) is None
    async with AsyncSessionLocal() as db:
        audit = (await db.execute(select(TicketAuditLog).where(TicketAuditLog.entity_id == s1))).scalar_one()
        assert audit.impersonator_id == admin_id
        completed = (
            await db.execute(
                select(RbacAuditLog).where(
                    RbacAuditLog.entity_id == str(rule.rule_id),
                    RbacAuditLog.action == "rule.run_now.completed",
                )
            )
        ).scalar_one()
        assert completed.user_id == world.users["satish"]
        assert completed.impersonator_id == admin_id
        assert '"succeeded_count": 1' in completed.new_value


async def test_two_users_triggering_the_same_rule_share_one_run(mail):
    world = await build_world()
    rule = await create_rule(world, "satish", [move(f"TU-{world.tag}")])
    by_site_lead = await update_rule(world, rule.rule_id, "site_lead", [move(f"TU-{world.tag}")], run_now=True)
    assert by_site_lead.active_run.run_id == rule.active_run.run_id
    async with AsyncSessionLocal() as db:
        count = (
            await db.execute(select(func.count()).select_from(RuleRun).where(RuleRun.rule_id == rule.rule_id))
        ).scalar_one()
    assert count == 1


async def test_latest_run_endpoint_reports_progress_and_enforces_access(mail):
    world = await build_world()
    await add_email(world, client="satish")
    rule = await create_rule(world, "satish", [move(f"LR-{world.tag}")])
    await drain()

    async def latest(actor: str):
        user = await principal(world.users[actor])
        async with AsyncSessionLocal() as db:
            service = RuleService(
                RuleRepository(db), MailFolderRepository(db), DistributionListRepository(db), InteractionRepository(db)
            )
            return await service.get_latest_run(rule.rule_id, current_user=user)

    summary = await latest("satish")
    assert summary.status == RuleRunStatus.COMPLETED
    assert summary.matched_count == 1 and summary.succeeded_count == 1
    with pytest.raises(HTTPException) as excinfo:
        await latest("ananya")  # not shared, no rule:view_all
    assert excinfo.value.status_code == 403


async def test_http_routes_round_trip_run_now_and_latest_run(mail):
    import httpx

    from app.database.session import get_db
    from app.dependencies.auth import get_current_agent
    from app.main import app

    world = await build_world()
    await add_email(world, client="satish")
    satish = await principal(world.users["satish"])

    async def _db():
        async with AsyncSessionLocal() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_current_agent] = lambda: satish
    app.dependency_overrides[get_db] = _db
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            created = await client.post(
                "/rules", json=_rule_payload(world, [move(f"HTTP-{world.tag}")], run_now=True)
            )
            assert created.status_code == 201, created.text
            body = created.json()
            assert body["active_run"]["status"] == "queued"
            assert "run_now" not in body

            await drain()

            latest = await client.get(f"/rules/{body['rule_id']}/runs/latest")
            assert latest.status_code == 200, latest.text
            summary = latest.json()
            assert summary["status"] == "completed"
            assert summary["succeeded_count"] == 1
            assert summary["run_id"] == body["active_run"]["run_id"]

            listed = await client.get("/rules")
            assert listed.status_code == 200
            mine = next(r for r in listed.json() if r["rule_id"] == body["rule_id"])
            assert mine["active_run"] is None  # finished -> no longer active
    finally:
        app.dependency_overrides.clear()
