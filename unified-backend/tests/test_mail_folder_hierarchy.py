# test_mail_folder_hierarchy.py
#
# DB-required coverage for nested (Outlook-style) mail folders:
# create subfolder / rename / move (subtree) / cycle protection /
# delete re-parenting / visibility of children / rule-bound rename
# guard. Runs against the configured database inside a transaction
# that is always rolled back — same convention as the other folder
# tests (point DATABASE_URL at the throwaway local Postgres).

import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from shared_models.models import User

from app.database.session import AsyncSessionLocal, engine
from app.ticketing.repositories.distribution_list_repository import (
    DistributionListRepository,
)
from app.ticketing.repositories.interaction_repository import InteractionRepository
from app.ticketing.repositories.mail_folder_repository import MailFolderRepository
from app.ticketing.repositories.rule_repository import RuleRepository
from app.ticketing.schemas.mail_folder import (
    MailFolderCreate,
    MailFolderMove,
    MailFolderRename,
)
from app.ticketing.services.mail_folder_service import MailFolderService


@pytest.fixture
async def db_session():
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.rollback()
    await engine.dispose()


async def _two_users(session) -> tuple[User, User]:
    result = await session.execute(select(User).where(User.is_active.is_(True)).limit(2))
    users = list(result.scalars().all())
    if len(users) < 2:
        pytest.skip("Need two active seeded users.")
    for u in users:
        u.permissions = []  # no rule:view_all -> created_by visibility only
    return users[0], users[1]


def _svc(session):
    return MailFolderService(MailFolderRepository(session)), RuleRepository(
        session
    ), DistributionListRepository(session)


def _n(prefix):
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


async def _create(session, user, name, parent=None):
    svc, rules, dls = _svc(session)
    return await svc.create(
        MailFolderCreate(name=name, parent_folder_id=parent), user, rules, dls
    )


async def test_root_sub_and_grandchild_creation(db_session):
    a, _ = await _two_users(db_session)
    root = await _create(db_session, a, _n("Clients"))
    child = await _create(db_session, a, _n("Active"), root.folder_id)
    grand = await _create(db_session, a, _n("High"), child.folder_id)
    assert root.parent_folder_id is None
    assert child.parent_folder_id == root.folder_id
    assert grand.parent_folder_id == child.folder_id


async def test_blank_name_rejected():
    with pytest.raises(ValueError):
        MailFolderCreate(name="   ")


async def test_duplicate_name_rejected_globally(db_session):
    a, _ = await _two_users(db_session)
    name = _n("Dup")
    root = await _create(db_session, a, name)
    with pytest.raises(HTTPException) as exc:
        await _create(db_session, a, name, root.folder_id)
    assert exc.value.status_code == 409


async def test_cannot_create_under_invisible_parent(db_session):
    a, b = await _two_users(db_session)
    private = await _create(db_session, a, _n("Private"))
    with pytest.raises(HTTPException) as exc:
        await _create(db_session, b, _n("Sneaky"), private.folder_id)
    assert exc.value.status_code == 404


async def test_rename_keeps_id_and_children(db_session):
    a, _ = await _two_users(db_session)
    svc, rules, dls = _svc(db_session)
    root = await _create(db_session, a, _n("Clients"))
    child = await _create(db_session, a, _n("Active"), root.folder_id)
    new_name = _n("Customers")
    renamed = await svc.rename(root.folder_id, MailFolderRename(name=new_name), a, rules, dls)
    assert renamed.folder_id == root.folder_id and renamed.name == new_name
    reloaded = await MailFolderRepository(db_session).get_by_id(child.folder_id)
    assert reloaded.parent_folder_id == root.folder_id


async def test_rename_to_existing_name_conflicts(db_session):
    a, _ = await _two_users(db_session)
    svc, rules, dls = _svc(db_session)
    one = await _create(db_session, a, _n("One"))
    two = await _create(db_session, a, _n("Two"))
    with pytest.raises(HTTPException) as exc:
        await svc.rename(two.folder_id, MailFolderRename(name=one.name), a, rules, dls)
    assert exc.value.status_code == 409


async def test_rename_unauthorized_is_404(db_session):
    a, b = await _two_users(db_session)
    svc, rules, dls = _svc(db_session)
    mine = await _create(db_session, a, _n("Mine"))
    with pytest.raises(HTTPException) as exc:
        await svc.rename(mine.folder_id, MailFolderRename(name=_n("X")), b, rules, dls)
    assert exc.value.status_code == 404


async def test_move_subtree_and_to_root(db_session):
    a, _ = await _two_users(db_session)
    svc, rules, dls = _svc(db_session)
    clients = await _create(db_session, a, _n("Clients"))
    projects = await _create(db_session, a, _n("Projects"))
    active = await _create(db_session, a, _n("Active"), clients.folder_id)
    high = await _create(db_session, a, _n("High"), active.folder_id)

    moved = await svc.move(
        active.folder_id, MailFolderMove(parent_folder_id=projects.folder_id), a, rules, dls
    )
    assert moved.folder_id == active.folder_id
    assert moved.parent_folder_id == projects.folder_id
    # Descendant untouched: still hangs off the moved folder.
    repo = MailFolderRepository(db_session)
    assert (await repo.get_by_id(high.folder_id)).parent_folder_id == active.folder_id

    to_root = await svc.move(
        active.folder_id, MailFolderMove(parent_folder_id=None), a, rules, dls
    )
    assert to_root.parent_folder_id is None


async def test_move_prevents_self_and_descendant_parent(db_session):
    a, _ = await _two_users(db_session)
    svc, rules, dls = _svc(db_session)
    clients = await _create(db_session, a, _n("Clients"))
    active = await _create(db_session, a, _n("Active"), clients.folder_id)
    high = await _create(db_session, a, _n("High"), active.folder_id)

    for target in (clients.folder_id, active.folder_id, high.folder_id):
        with pytest.raises(HTTPException) as exc:
            await svc.move(
                clients.folder_id, MailFolderMove(parent_folder_id=target), a, rules, dls
            )
        assert exc.value.status_code == 400


async def test_move_unauthorized(db_session):
    a, b = await _two_users(db_session)
    svc, rules, dls = _svc(db_session)
    mine = await _create(db_session, a, _n("Mine"))
    theirs = await _create(db_session, b, _n("Theirs"))
    # b cannot move a's folder, nor move own folder under a's.
    with pytest.raises(HTTPException) as e1:
        await svc.move(mine.folder_id, MailFolderMove(parent_folder_id=None), b, rules, dls)
    assert e1.value.status_code == 404
    with pytest.raises(HTTPException) as e2:
        await svc.move(
            theirs.folder_id, MailFolderMove(parent_folder_id=mine.folder_id), b, rules, dls
        )
    assert e2.value.status_code == 404


async def test_delete_reparents_children_and_keeps_them(db_session):
    a, _ = await _two_users(db_session)
    svc, rules, dls = _svc(db_session)
    clients = await _create(db_session, a, _n("Clients"))
    active = await _create(db_session, a, _n("Active"), clients.folder_id)
    high = await _create(db_session, a, _n("High"), active.folder_id)

    await svc.delete(
        active.folder_id, a, rules, dls, InteractionRepository(db_session)
    )
    repo = MailFolderRepository(db_session)
    assert await repo.get_by_id(active.folder_id) is None
    assert (await repo.get_by_id(high.folder_id)).parent_folder_id == clients.folder_id

    await svc.delete(clients.folder_id, a, rules, dls, InteractionRepository(db_session))
    assert (await repo.get_by_id(high.folder_id)).parent_folder_id is None


async def test_delete_unauthorized(db_session):
    a, b = await _two_users(db_session)
    svc, rules, dls = _svc(db_session)
    mine = await _create(db_session, a, _n("Mine"))
    with pytest.raises(HTTPException) as exc:
        await svc.delete(mine.folder_id, b, rules, dls, InteractionRepository(db_session))
    assert exc.value.status_code == 404


async def test_existing_folders_are_roots(db_session):
    # Pre-existing rows (no parent set) stay root folders.
    repo = MailFolderRepository(db_session)
    legacy = await repo.create(_n("Legacy"), None)
    assert legacy.parent_folder_id is None
