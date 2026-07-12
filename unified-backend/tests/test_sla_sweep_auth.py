# test_sla_sweep_auth.py
#
# POST /internal/sla/sweep is protected by a shared-secret header, not
# JWT (there's no "user" behind a cron tick) — this exercises the
# dependency directly rather than spinning up the full app/DB, since
# the auth check itself has no database dependency.

import pytest
from fastapi import HTTPException

from app.core.config import get_settings
from app.ticketing.api.sla_internal import verify_sla_sweep_secret


async def test_correct_secret_passes():
    settings = get_settings()

    # Should not raise.
    await verify_sla_sweep_secret(x_sla_sweep_secret=settings.sla_sweep_shared_secret)


async def test_wrong_secret_is_rejected():
    with pytest.raises(HTTPException) as exc_info:
        await verify_sla_sweep_secret(x_sla_sweep_secret="definitely-not-the-secret")

    assert exc_info.value.status_code == 401


async def test_empty_secret_is_rejected():
    with pytest.raises(HTTPException) as exc_info:
        await verify_sla_sweep_secret(x_sla_sweep_secret="")

    assert exc_info.value.status_code == 401
