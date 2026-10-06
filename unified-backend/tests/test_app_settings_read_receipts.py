# test_app_settings_read_receipts.py
#
# The global Read Receipts setting (table `app_settings`, Settings > Email &
# Communication): default OFF, who may read/change it, persistence across
# sessions ("restart"), the audit trail, fail-closed behaviour, and its
# effect on what is actually sent to Graph.
#
# Real-DB (rolled-back) like the other read-receipt DB tests: needs a
# database migrated to head and seeded roles, DATABASE_URL pointed at a
# THROWAWAY database (never the shared RDS). Skipped when `app_settings` is
# absent. The persistence-across-sessions test commits and cleans up after
# itself.

import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import select, text

from app.database.session import AsyncSessionLocal, engine
from app.rbac.models.audit_log import AuditLog
from app.ticketing.api import app_settings as settings_api
from app.ticketing.models.app_setting import AppSetting
from app.ticketing.services import interaction_service as interaction_service_module
from app.ticketing.services.app_settings_service import (
    APP_SETTINGS_MANAGE_PERMISSION,
    READ_RECEIPTS_ENABLED_KEY,
    is_read_receipts_enabled,
    set_read_receipts_enabled,
)
from app.ticketing.services.interaction_service import _effective_read_receipt_requested
from tests.test_mail_otp_section import _make_user


@pytest.fixture
async def db_session():
    async with AsyncSessionLocal() as session:
        try:
            probe = await session.execute(
                text(
                    "select count(*) from information_schema.tables "
                    "where table_name = 'app_settings'"
                )
            )
            if probe.scalar_one() == 0:
                pytest.skip("database is not migrated to the app_settings revision")
            # A previous interrupted run must not leak state into the default test.
            existing = (
                await session.execute(
                    select(AppSetting).where(AppSetting.key == READ_RECEIPTS_ENABLED_KEY)
                )
            ).scalar_one_or_none()
            if existing is not None:
                pytest.skip("app_settings already holds a read-receipts row in this database")
            yield session
        finally:
            await session.rollback()
    await engine.dispose()


async def _admin(session):
    return await _make_user(session, "Super Admin", "SettingsAdmin", [APP_SETTINGS_MANAGE_PERMISSION])


async def _staff(session):
    return await _make_user(session, "Staff", "SettingsStaff", ["communication:reply_external"])


# ---------------------------------------------------------------
# Default and storage
# ---------------------------------------------------------------


async def test_default_is_off_when_nothing_has_ever_been_saved(db_session):
    assert await is_read_receipts_enabled(db_session) is False


async def test_set_and_read_back_and_overwrite(db_session):
    admin = await _admin(db_session)

    assert await set_read_receipts_enabled(db_session, True, admin.user_id) is True
    assert await is_read_receipts_enabled(db_session) is True

    assert await set_read_receipts_enabled(db_session, False, admin.user_id) is False
    assert await is_read_receipts_enabled(db_session) is False

    rows = (await db_session.execute(select(AppSetting))).scalars().all()
    assert [r.key for r in rows if r.key == READ_RECEIPTS_ENABLED_KEY] == [READ_RECEIPTS_ENABLED_KEY]
    row = next(r for r in rows if r.key == READ_RECEIPTS_ENABLED_KEY)
    assert row.updated_by == admin.user_id and row.updated_at is not None


@pytest.mark.parametrize("junk", ["true", 1, "yes", None, [], {"enabled": True}])
async def test_anything_other_than_boolean_true_reads_as_off(db_session, junk):
    db_session.add(AppSetting(key=READ_RECEIPTS_ENABLED_KEY, value=junk))
    await db_session.flush()

    assert await is_read_receipts_enabled(db_session) is False


async def test_a_failing_lookup_fails_closed_and_never_raises():
    class _BrokenDb:
        def begin_nested(self):
            raise RuntimeError("relation app_settings does not exist")

    assert await is_read_receipts_enabled(_BrokenDb()) is False


async def test_setting_persists_across_sessions_like_a_restart():
    async with AsyncSessionLocal() as probe:
        exists = await probe.execute(
            text("select count(*) from information_schema.tables where table_name='app_settings'")
        )
        if exists.scalar_one() == 0:
            pytest.skip("database is not migrated to the app_settings revision")
        if (
            await probe.execute(
                select(AppSetting).where(AppSetting.key == READ_RECEIPTS_ENABLED_KEY)
            )
        ).scalar_one_or_none() is not None:
            pytest.skip("app_settings already holds a read-receipts row in this database")

    try:
        async with AsyncSessionLocal() as writer:
            await set_read_receipts_enabled(writer, True, None)
            await writer.commit()
        await engine.dispose()  # drop every pooled connection: "the process restarted"

        async with AsyncSessionLocal() as fresh:
            assert await is_read_receipts_enabled(fresh) is True
    finally:
        async with AsyncSessionLocal() as cleanup:
            await cleanup.execute(
                text("delete from app_settings where key = :k"), {"k": READ_RECEIPTS_ENABLED_KEY}
            )
            await cleanup.commit()
        await engine.dispose()


# ---------------------------------------------------------------
# API and RBAC
# ---------------------------------------------------------------


async def test_admin_can_read_the_setting(db_session):
    admin = await _admin(db_session)

    response = await settings_api.get_read_receipt_setting(current_user=admin, db=db_session)

    assert response.read_receipts_enabled is False  # default OFF
    assert response.can_manage is True


async def test_a_non_admin_can_read_but_is_told_they_cannot_manage(db_session):
    staff = await _staff(db_session)

    response = await settings_api.get_read_receipt_setting(current_user=staff, db=db_session)

    assert response.read_receipts_enabled is False
    assert response.can_manage is False


async def test_admin_can_update_the_setting_and_it_takes_effect(db_session):
    admin = await _admin(db_session)

    on = await settings_api.update_read_receipt_setting(
        settings_api.ReadReceiptSettingUpdate(enabled=True), current_user=admin, db=db_session
    )
    assert on.read_receipts_enabled is True and on.can_manage is True
    assert await is_read_receipts_enabled(db_session) is True
    assert (
        await settings_api.get_read_receipt_setting(current_user=admin, db=db_session)
    ).read_receipts_enabled is True

    off = await settings_api.update_read_receipt_setting(
        settings_api.ReadReceiptSettingUpdate(enabled=False), current_user=admin, db=db_session
    )
    assert off.read_receipts_enabled is False
    assert await is_read_receipts_enabled(db_session) is False


@pytest.mark.parametrize("role", ["Staff", "Team Lead", "Account Manager", "Site Lead"])
async def test_users_without_the_permission_cannot_update_it(db_session, role):
    user = await _make_user(
        db_session, role, f"NoCfg{role.replace(' ', '')}",
        ["communication:reply_external", "communication:create", "ticket:assign"],
    )

    with pytest.raises(HTTPException) as caught:
        await settings_api.update_read_receipt_setting(
            settings_api.ReadReceiptSettingUpdate(enabled=True), current_user=user, db=db_session
        )

    assert caught.value.status_code == 403
    assert await is_read_receipts_enabled(db_session) is False  # unchanged


async def test_by_default_only_super_admin_holds_the_manage_permission(db_session):
    # Documents the seeded RBAC default this feature relies on: Staff (and
    # every other role) cannot change the global switch automatically.
    rows = (
        await db_session.execute(
            text(
                "select distinct r.name from roles r "
                "join role_permissions rp on rp.role_id = r.role_id "
                "join permissions p on p.permission_id = rp.permission_id "
                "where p.permission_name = :p"
            ),
            {"p": APP_SETTINGS_MANAGE_PERMISSION},
        )
    ).all()
    assert {r[0] for r in rows} == {"Super Admin"}


async def test_every_change_is_recorded_in_the_audit_log(db_session):
    admin = await _admin(db_session)
    await settings_api.update_read_receipt_setting(
        settings_api.ReadReceiptSettingUpdate(enabled=True), current_user=admin, db=db_session
    )

    log = (
        await db_session.execute(
            select(AuditLog).where(
                AuditLog.user_id == admin.user_id,
                AuditLog.action == "settings.read_receipts_updated",
            )
        )
    ).scalar_one()
    assert (log.entity_type, log.entity_id) == ("app_setting", READ_RECEIPTS_ENABLED_KEY)
    assert (log.old_value, log.new_value) == ("false", "true")


async def test_an_audit_failure_never_loses_the_setting_change(db_session, monkeypatch):
    admin = await _admin(db_session)

    async def _boom(self, log_data):
        raise RuntimeError("audit table unavailable")

    monkeypatch.setattr(settings_api.AuditLogService, "create_log", _boom)
    response = await settings_api.update_read_receipt_setting(
        settings_api.ReadReceiptSettingUpdate(enabled=True), current_user=admin, db=db_session
    )

    assert response.read_receipts_enabled is True
    assert await is_read_receipts_enabled(db_session) is True


def test_the_settings_routes_are_registered_and_the_update_is_a_put():
    methods = {(r.path, tuple(sorted(r.methods))) for r in settings_api.router.routes}
    assert ("/app-settings/read-receipts", ("GET",)) in methods
    assert ("/app-settings/read-receipts", ("PUT",)) in methods


# ---------------------------------------------------------------
# Effect on sending (real DB setting -> effective flag)
# ---------------------------------------------------------------


async def test_off_blocks_a_requested_receipt_and_on_allows_it(db_session):
    admin = await _admin(db_session)

    # Default OFF: a client-supplied flag is ignored.
    assert await _effective_read_receipt_requested(db_session, True) is False

    await set_read_receipts_enabled(db_session, True, admin.user_id)
    assert await _effective_read_receipt_requested(db_session, True) is True
    assert await _effective_read_receipt_requested(db_session, False) is False  # not asked

    await set_read_receipts_enabled(db_session, False, admin.user_id)
    assert await _effective_read_receipt_requested(db_session, True) is False


def test_interaction_service_no_longer_reads_any_environment_flag():
    import inspect

    source = inspect.getsource(interaction_service_module)
    assert "read_receipts_enabled" not in source.replace("is_read_receipts_enabled", "")
