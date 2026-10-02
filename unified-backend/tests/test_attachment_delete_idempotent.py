# test_attachment_delete_idempotent.py
#
# Regression coverage for a reported "Network Error" when removing a
# draft attachment: deleting the storage object raised (Supabase answers
# 400 for an object that is already gone) and nothing handled it, so the
# request ended in an unhandled 500 — which a browser reports as a bare
# network/CORS failure — and the DB row could never be removed on retry.
# AttachmentService.delete_attachment must stay repeatable.
#
# Pure unit tests: collaborators are mocks, nothing touches the database
# or real storage.

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.ticketing.services import attachment_service as module
from app.ticketing.services.attachment_service import AttachmentService


def _service(storage):
    attachment = SimpleNamespace(
        attachment_id=uuid4(),
        interaction_id=uuid4(),
        filename="image.png",
        mime_type="image/png",
        size_bytes=10,
        storage_key="2026/10/abc-image.png",
        is_external_link=False,
    )
    attachment_repository = MagicMock()
    attachment_repository.delete = AsyncMock()
    attachment_repository.db = MagicMock()
    interaction_repository = MagicMock()
    interaction_repository.get_by_id = AsyncMock(return_value=SimpleNamespace(ticket_id=None))
    service = AttachmentService(
        attachment_repository=attachment_repository,
        interaction_repository=interaction_repository,
        ticket_repository=MagicMock(),
        storage_service=storage,
    )
    service._resolve_and_authorize = AsyncMock(return_value=attachment)
    return service, attachment, attachment_repository


async def _delete(service, attachment):
    user = MagicMock()
    with patch.object(module, "ensure_has_permission"), patch.object(
        module.AuditLogService, "log_event", new=AsyncMock()
    ), patch.object(
        module.AuditLogService, "resolve_agent_actor", return_value=(uuid4(), "n", "r")
    ):
        await service.delete_attachment(attachment.attachment_id, current_user=user)


async def test_normal_delete_removes_object_and_row():
    storage = MagicMock(delete=AsyncMock(), exists=AsyncMock())
    service, attachment, repo = _service(storage)
    await _delete(service, attachment)
    storage.delete.assert_awaited_once_with(object_key=attachment.storage_key)
    repo.delete.assert_awaited_once_with(attachment)
    storage.exists.assert_not_awaited()


async def test_already_gone_object_does_not_block_removing_the_row():
    storage = MagicMock(
        delete=AsyncMock(side_effect=RuntimeError("400 Bad Request")),
        exists=AsyncMock(return_value=False),
    )
    service, attachment, repo = _service(storage)
    await _delete(service, attachment)
    repo.delete.assert_awaited_once_with(attachment)


async def test_real_storage_failure_is_still_raised_and_row_kept():
    storage = MagicMock(
        delete=AsyncMock(side_effect=RuntimeError("storage down")),
        exists=AsyncMock(return_value=True),
    )
    service, attachment, repo = _service(storage)
    with pytest.raises(RuntimeError, match="storage down"):
        await _delete(service, attachment)
    repo.delete.assert_not_awaited()


async def test_unverifiable_storage_state_is_treated_as_a_failure():
    storage = MagicMock(
        delete=AsyncMock(side_effect=RuntimeError("storage down")),
        exists=AsyncMock(side_effect=RuntimeError("also down")),
    )
    service, attachment, repo = _service(storage)
    with pytest.raises(RuntimeError, match="storage down"):
        await _delete(service, attachment)
    repo.delete.assert_not_awaited()
