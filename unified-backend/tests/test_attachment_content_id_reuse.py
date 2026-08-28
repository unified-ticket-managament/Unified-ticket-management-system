# test_attachment_content_id_reuse.py
#
# Regression coverage for the inbound-mail-ingestion bug where an
# email's inline image reusing a Content-ID Microsoft Graph already
# returned on a previously-stored, unrelated message (normal Outlook
# behavior for a signature/logo image — the Content-ID is generated
# once by the sender's client and stays identical across every message
# that embeds it) hit `ix_attachments_content_id`'s database-level
# unique constraint on INSERT. AttachmentService.validate_and_store_files's
# `tolerate_failures` flag only ever wrapped the pre-DB validation
# steps (type/size/magic-bytes), never the actual
# `attachment_repository.create(...)` call, so the resulting
# IntegrityError propagated all the way up through
# EmailService.receive_email into the poller, which rolled back the
# *entire* transaction — the whole inbound email, not just its
# attachment, silently vanished, retried and re-failing identically on
# every subsequent poll tick forever. Confirmed live against the
# `inbound_mail_failures` table (3+ mailboxes, dozens of retries).
#
# Runs against the real (dev) database inside a transaction that is
# always rolled back at the end — same convention as
# test_ticket_attachments.py/test_attachment_upload_authorization.py.

import uuid
from datetime import datetime, timezone

import pytest

from app.database.session import AsyncSessionLocal, engine
from app.ticketing.enums import InteractionDirection
from app.ticketing.models.interaction import Interaction
from app.ticketing.repositories.attachment_repository import AttachmentRepository
from app.ticketing.repositories.interaction_repository import InteractionRepository
from app.ticketing.repositories.ticket_repository import TicketRepository
from app.ticketing.services.attachment_service import AttachmentService
from app.ticketing.storage.base import StorageService


class FakeStorageService(StorageService):
    bucket = "test-bucket"

    def __init__(self):
        self._objects: dict[str, bytes] = {}

    async def upload(self, *, data: bytes, object_key: str, content_type: str) -> None:
        self._objects[object_key] = data

    async def download(self, *, object_key: str) -> bytes:
        return self._objects[object_key]

    async def delete(self, *, object_key: str) -> None:
        self._objects.pop(object_key, None)

    async def exists(self, *, object_key: str) -> bool:
        return object_key in self._objects

    async def presigned_get_url(
        self, *, object_key: str, filename: str, inline: bool = False
    ) -> str:
        return f"https://fake-storage.test/{object_key}"


class FakeUploadFile:
    def __init__(
        self,
        filename: str,
        content: bytes,
        content_type: str,
        content_id: str | None = None,
        is_inline: bool = False,
    ):
        self.filename = filename
        self.content_type = content_type
        self._content = content
        self.content_id = content_id
        self.is_inline = is_inline

    async def read(self) -> bytes:
        return self._content


@pytest.fixture
async def db_session():
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.rollback()
    await engine.dispose()


async def _make_bare_interaction(session) -> Interaction:
    # No ticket, no performed_by — mirrors a pre-ticket inbound-mail
    # Interaction (Mail thread), the exact shape EmailService.receive_email
    # persists for a Graph-sourced message. Only what
    # validate_and_store_files/the attachments FK actually need.
    interaction = Interaction(
        interaction_id=uuid.uuid4(),
        ticket_id=None,
        interaction_type="EMAIL",
        direction=InteractionDirection.INBOUND,
        performed_by=None,
        payload={},
        created_at=datetime.now(timezone.utc),
    )
    session.add(interaction)
    await session.flush()
    return interaction


def _build_service(session) -> AttachmentService:
    return AttachmentService(
        attachment_repository=AttachmentRepository(session),
        interaction_repository=InteractionRepository(session),
        ticket_repository=TicketRepository(session),
        storage_service=FakeStorageService(),
    )


async def test_reused_inline_content_id_across_interactions_does_not_drop_either_email(
    db_session,
):
    """
    Two DIFFERENT inbound emails (two different Interaction rows) each
    embedding the same recurring signature image (same Graph
    contentId) — normal, expected behavior, not a bug in the inbound
    mail. Both must persist successfully; storing the second must not
    raise past validate_and_store_files, since that would (pre-fix)
    unwind the whole receive_email transaction for that email.
    """

    service = _build_service(db_session)
    shared_content_id = f"image001.jpg@{uuid.uuid4().hex}"

    first_interaction = await _make_bare_interaction(db_session)
    first_files = await service.validate_and_store_files(
        [
            FakeUploadFile(
                "image001.txt",
                b"fake-inline-image-bytes",
                "text/plain",
                content_id=shared_content_id,
                is_inline=True,
            )
        ],
        interaction_id=first_interaction.interaction_id,
        tolerate_failures=True,
    )

    assert len(first_files) == 1
    assert first_files[0].content_id == shared_content_id

    second_interaction = await _make_bare_interaction(db_session)
    second_files = await service.validate_and_store_files(
        [
            FakeUploadFile(
                "image001.txt",
                b"fake-inline-image-bytes",
                "text/plain",
                content_id=shared_content_id,
                is_inline=True,
            )
        ],
        interaction_id=second_interaction.interaction_id,
        tolerate_failures=True,
    )

    # Pre-fix: this raised IntegrityError out of validate_and_store_files
    # (ix_attachments_content_id, table-wide unique), which propagated
    # all the way up through EmailService.receive_email and rolled back
    # the second interaction's entire transaction — the email vanished
    # with no attachment AND no Interaction row at all.
    assert len(second_files) == 1
    assert second_files[0].content_id == shared_content_id
    assert second_files[0].interaction_id == second_interaction.interaction_id


async def test_attachment_collision_never_drops_the_interaction_itself(db_session):
    """
    What Fix 0b's SAVEPOINT guarantees independent of Fix 0a's index
    rescoping: even a *still-genuine* content_id collision (two
    attachments on the SAME interaction — the one case the rescoped
    per-interaction index still, correctly, rejects; see the control
    test below) never takes the Interaction row down with it. Only
    the failed attachment's own SAVEPOINT is rolled back, not the
    surrounding transaction. Pre-Fix-0b, the bare IntegrityError from
    attachment_repository.create propagated out of
    validate_and_store_files uncaught, which in the real inbound-mail
    path (EmailService.receive_email, called from
    graph_mail_poller._poll_one_mailbox) rolled back the *entire*
    per-message transaction — the Interaction row along with it — so
    the email vanished completely, not just its attachment.
    """

    service = _build_service(db_session)
    interaction = await _make_bare_interaction(db_session)
    shared_content_id = f"image001.jpg@{uuid.uuid4().hex}"

    files = await service.validate_and_store_files(
        [
            FakeUploadFile(
                "image001.txt",
                b"fake-inline-image-bytes-a",
                "text/plain",
                content_id=shared_content_id,
                is_inline=True,
            ),
            FakeUploadFile(
                "image001-copy.txt",
                b"fake-inline-image-bytes-b",
                "text/plain",
                content_id=shared_content_id,
                is_inline=True,
            ),
        ],
        interaction_id=interaction.interaction_id,
        tolerate_failures=True,
    )

    # The second attachment genuinely collided (same interaction, same
    # content_id) and was dropped — but critically, the session/
    # transaction is still usable afterward and the Interaction row
    # itself was never rolled back, unlike the pre-Fix-0b behavior.
    assert len(files) == 1
    reloaded = await InteractionRepository(db_session).get_by_id(interaction.interaction_id)
    assert reloaded is not None


async def test_reused_content_id_within_the_same_interaction_still_dropped(db_session):
    """
    Control case: the invariant that actually matters — a `cid:`
    reference must resolve unambiguously within one message's own
    body — is still preserved. Two attachments on the SAME interaction
    with the same content_id can't both be stored; the second is
    logged and dropped (tolerate_failures semantics), not silently
    duplicated.
    """

    service = _build_service(db_session)
    interaction = await _make_bare_interaction(db_session)
    shared_content_id = f"image001.jpg@{uuid.uuid4().hex}"

    files = await service.validate_and_store_files(
        [
            FakeUploadFile(
                "image001.txt",
                b"fake-inline-image-bytes-a",
                "text/plain",
                content_id=shared_content_id,
                is_inline=True,
            ),
            FakeUploadFile(
                "image001-copy.txt",
                b"fake-inline-image-bytes-b",
                "text/plain",
                content_id=shared_content_id,
                is_inline=True,
            ),
        ],
        interaction_id=interaction.interaction_id,
        tolerate_failures=True,
    )

    assert len(files) == 1
    assert files[0].content_id == shared_content_id


async def test_non_tolerant_callers_still_raise_on_duplicate_content_id(db_session):
    """
    The composer-paste path (tolerate_failures defaults to False) must
    keep its original behavior unchanged: a genuine duplicate
    server-minted content_id (the case ix_attachments_content_id was
    actually designed to guard against) still surfaces as a real
    error rather than being silently swallowed.
    """
    from sqlalchemy.exc import IntegrityError

    service = _build_service(db_session)
    interaction = await _make_bare_interaction(db_session)
    shared_content_id = f"pasted-{uuid.uuid4().hex}"

    await service.validate_and_store_files(
        [
            FakeUploadFile(
                "paste.txt",
                b"fake-paste-bytes",
                "text/plain",
                content_id=shared_content_id,
                is_inline=True,
            )
        ],
        interaction_id=interaction.interaction_id,
        tolerate_failures=False,
    )

    with pytest.raises(IntegrityError):
        await service.validate_and_store_files(
            [
                FakeUploadFile(
                    "paste2.txt",
                    b"fake-paste-bytes-2",
                    "text/plain",
                    content_id=shared_content_id,
                    is_inline=True,
                )
            ],
            interaction_id=interaction.interaction_id,
            tolerate_failures=False,
        )
