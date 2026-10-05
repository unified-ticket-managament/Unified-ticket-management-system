# test_email_signature_service.py
#
# Pure-logic coverage for EmailSignatureService (multiple signatures,
# one default) — no DB, no real object storage. A fake repository
# stands in for EmailSignatureRepository with the same user-scoped
# semantics, including the "at most one default per user" invariant
# the real partial unique index enforces (asserted after every write).

import importlib.util
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.rbac.models.email_signature import EmailSignature, EmailSignatureImage
from app.rbac.schemas.email_signature import EmailSignatureCreate, EmailSignatureUpdate
from app.rbac.services.email_signature_service import (
    COMPANY_LOGO_BLOCK_HTML,
    EmailSignatureService,
    legacy_signature_with_logo,
)
from app.ticketing.services.signature_inline_images import (
    SIGNATURE_IMAGE_KEY_PREFIX,
    signature_image_content_id,
)


class _FakeSignatureRepository:
    def __init__(self):
        self.signatures: list[EmailSignature] = []
        self.images: list[EmailSignatureImage] = []
        self.attachment_keys: set[str] = set()
        self.draft_content_ids: dict = {}
        self.locked: list = []
        self._seq = 0

    def _assert_single_default(self):
        defaults: dict = {}
        for s in self.signatures:
            if s.is_default:
                assert s.user_id not in defaults, "two defaults for one user"
                defaults[s.user_id] = s

    async def lock_user(self, user_id):
        self.locked.append(user_id)

    async def list_for_user(self, user_id):
        return [s for s in self.signatures if s.user_id == user_id]

    async def get_for_user(self, user_id, signature_id):
        return next(
            (s for s in self.signatures if s.user_id == user_id and s.signature_id == signature_id),
            None,
        )

    async def add(self, signature):
        self._seq += 1
        now = datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=self._seq)
        signature.signature_id = signature.signature_id or uuid4()
        signature.created_at = now
        signature.updated_at = now
        self.signatures.append(signature)
        self._assert_single_default()
        return signature

    async def save(self, signature):
        self._assert_single_default()
        return signature

    async def delete(self, signature):
        self.signatures.remove(signature)

    async def clear_default(self, user_id):
        for s in self.signatures:
            if s.user_id == user_id:
                s.is_default = False

    async def add_image(self, image):
        image.created_at = datetime.now(timezone.utc)
        self.images.append(image)
        return image

    async def list_images_by_ids(self, user_id, image_ids):
        return [i for i in self.images if i.user_id == user_id and i.image_id in image_ids]

    async def list_images_created_before(self, user_id, cutoff):
        return [i for i in self.images if i.user_id == user_id and i.created_at < cutoff]

    async def is_storage_key_used_by_attachment(self, storage_key):
        return storage_key in self.attachment_keys

    async def is_content_id_in_user_drafts(self, user_id, content_id):
        return content_id in self.draft_content_ids.get(user_id, set())

    async def delete_image(self, image):
        self.images.remove(image)


class _FakeUserRepository:
    def __init__(self, signature_html_by_user=None):
        self.signature_html_by_user = signature_html_by_user or {}

    async def get_by_id(self, user_id):
        return SimpleNamespace(signature_html=self.signature_html_by_user.get(user_id))


class _FakeStorage:
    bucket = "test-bucket"

    def __init__(self):
        self.uploaded: dict[str, bytes] = {}
        self.deleted: list[str] = []

    async def upload(self, *, data, object_key, content_type):
        self.uploaded[object_key] = data

    async def delete(self, *, object_key):
        self.deleted.append(object_key)

    async def presigned_get_url(self, *, object_key, filename, inline=False):
        return f"https://storage.example/{object_key}"


class _FakeUpload:
    def __init__(self, filename, content_type, data):
        self.filename = filename
        self.content_type = content_type
        self._data = data

    async def read(self):
        return self._data


PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


@pytest.fixture(autouse=True)
def _fake_magic(monkeypatch):
    # Same approach as test_attachment_magic_validation.py: never touch
    # the host's real libmagic (absent or hanging on dev machines).
    fake = SimpleNamespace(from_buffer=lambda data, mime=True: _fake_magic.sniffed)
    _fake_magic.sniffed = "image/png"
    monkeypatch.setitem(sys.modules, "magic", fake)


async def test_image_upload_rejects_content_that_is_not_really_an_image():
    service, repo = _service(storage=_FakeStorage())
    _fake_magic.sniffed = "application/x-dosexec"
    with pytest.raises(HTTPException) as exc:
        await service.upload_image(_user(), _FakeUpload("logo.png", "image/png", b"MZ" + b"\x00" * 64))
    assert exc.value.status_code == 415
    assert repo.images == []


def _user(user_id=None, impersonator_id=None):
    return SimpleNamespace(user_id=user_id or uuid4(), impersonator_id=impersonator_id)


def _service(legacy=None, storage=None):
    repo = _FakeSignatureRepository()
    service = EmailSignatureService(
        signature_repository=repo,
        user_repository=_FakeUserRepository(legacy),
        storage_service=storage,
    )
    return service, repo


async def _create(service, user, name, html="<p>Regards,<br>Hari</p>", **kw):
    return await service.create_signature(user, EmailSignatureCreate(name=name, html=html, **kw))


# ---------------- default rules ----------------


async def test_first_signature_automatically_becomes_default():
    service, repo = _service()
    user = _user()

    created = await _create(service, user, "Probe")

    assert created.is_default is True
    listing = await service.list_signatures(user)
    assert listing.default_signature_id == created.signature_id


async def test_second_signature_does_not_replace_default():
    service, _ = _service()
    user = _user()
    first = await _create(service, user, "Probe")

    second = await _create(service, user, "Carolina Psychiatry")

    assert second.is_default is False
    listing = await service.list_signatures(user)
    assert listing.default_signature_id == first.signature_id


async def test_set_default_moves_default_and_old_default_is_cleared():
    service, repo = _service()
    user = _user()
    first = await _create(service, user, "Probe")
    second = await _create(service, user, "Carolina")

    await service.set_default(user, second.signature_id)

    by_id = {s.signature_id: s for s in repo.signatures}
    assert by_id[second.signature_id].is_default is True
    assert by_id[first.signature_id].is_default is False
    assert sum(s.is_default for s in repo.signatures) == 1
    assert repo.locked, "mutations must serialize on the user row"


async def test_create_with_explicit_default_still_leaves_one_default():
    service, repo = _service()
    user = _user()
    await _create(service, user, "Probe")

    third = await _create(service, user, "Personal", is_default=True)

    assert third.is_default is True
    assert sum(s.is_default for s in repo.signatures) == 1


async def test_edit_signature_updates_name_and_html():
    service, repo = _service()
    user = _user()
    sig = await _create(service, user, "Probe")

    updated = await service.update_signature(
        user,
        sig.signature_id,
        EmailSignatureUpdate(name="Probe PS", html="<p>Regards,<br>Hari Krishna<br>Senior AM</p>"),
    )

    assert updated.name == "Probe PS"
    assert "Hari Krishna" in updated.html
    assert updated.is_default is True


async def test_duplicate_name_is_rejected_case_insensitively():
    service, _ = _service()
    user = _user()
    await _create(service, user, "Probe")

    with pytest.raises(HTTPException) as exc:
        await _create(service, user, "  probe ")
    assert exc.value.status_code == 409


async def test_delete_non_default_keeps_default():
    service, repo = _service()
    user = _user()
    first = await _create(service, user, "Probe")
    second = await _create(service, user, "Carolina")

    await service.delete_signature(user, second.signature_id)

    assert [s.signature_id for s in repo.signatures] == [first.signature_id]
    assert repo.signatures[0].is_default is True


async def test_delete_default_promotes_another_signature():
    service, repo = _service()
    user = _user()
    first = await _create(service, user, "Probe")
    second = await _create(service, user, "Carolina")
    third = await _create(service, user, "Personal")

    await service.delete_signature(user, first.signature_id)

    remaining = {s.signature_id: s.is_default for s in repo.signatures}
    assert first.signature_id not in remaining
    assert remaining == {second.signature_id: True, third.signature_id: False}


async def test_delete_last_signature_falls_back_to_legacy_default():
    user = _user()
    legacy = "<div>Regards,<br>Hari</div>"
    service, repo = _service(legacy={user.user_id: legacy})
    only = await _create(service, user, "Probe")

    await service.delete_signature(user, only.signature_id)

    listing = await service.list_signatures(user)
    assert listing.signatures == []
    assert listing.default_signature_id is None
    assert listing.fallback_signature_html == legacy + COMPANY_LOGO_BLOCK_HTML


async def test_no_signatures_and_no_legacy_signature_has_no_fallback():
    service, _ = _service()
    listing = await service.list_signatures(_user())
    assert listing.fallback_signature_html is None


async def test_fallback_is_not_offered_once_user_has_signatures():
    user = _user()
    service, _ = _service(legacy={user.user_id: "<div>old</div>"})
    await _create(service, user, "Probe")

    listing = await service.list_signatures(user)
    assert listing.fallback_signature_html is None


# ---------------- authorization / effective user ----------------


async def test_user_cannot_see_or_modify_another_users_signatures():
    service, repo = _service()
    owner = _user()
    intruder = _user()
    sig = await _create(service, owner, "Probe")

    assert (await service.list_signatures(intruder)).signatures == []
    for call in (
        service.update_signature(intruder, sig.signature_id, EmailSignatureUpdate(name="x")),
        service.delete_signature(intruder, sig.signature_id),
        service.set_default(intruder, sig.signature_id),
    ):
        with pytest.raises(HTTPException) as exc:
            await call
        assert exc.value.status_code == 404
    assert repo.signatures[0].name == "Probe"


async def test_impersonation_acts_on_the_effective_user_not_the_actor():
    service, repo = _service()
    admin_id = uuid4()
    target = _user(impersonator_id=admin_id)

    created = await _create(service, target, "Impersonated")

    assert created.signature_id in {s.signature_id for s in repo.signatures}
    assert all(s.user_id == target.user_id for s in repo.signatures)
    assert (await service.list_signatures(_user(user_id=admin_id))).signatures == []


# ---------------- sanitization / images ----------------


async def test_signature_html_is_sanitized():
    service, _ = _service()
    created = await _create(
        service,
        _user(),
        "Probe",
        html=(
            '<p onclick="steal()">Regards<script>alert(1)</script></p>'
            '<a href="javascript:alert(1)">x</a><iframe src="https://evil"></iframe>'
        ),
    )
    assert "script" not in created.html
    assert "onclick" not in created.html
    assert "javascript:" not in created.html
    assert "iframe" not in created.html
    assert "Regards" in created.html


async def test_remote_or_data_images_are_rejected():
    service, _ = _service()
    for src in ("https://tracker.example/p.png", "data:image/png;base64,AAAA", "/local.png"):
        with pytest.raises(HTTPException) as exc:
            await _create(service, _user(), "Probe", html=f'<p>Hi</p><img src="{src}">')
        assert exc.value.status_code == 400


async def test_company_logo_reference_is_allowed():
    service, _ = _service()
    created = await _create(service, _user(), "Probe", html="<p>Regards</p>" + COMPANY_LOGO_BLOCK_HTML)
    assert "cid:company-signature-logo-v1" in created.html


async def test_another_users_signature_image_is_rejected():
    storage = _FakeStorage()
    service, _ = _service(storage=storage)
    owner, other = _user(), _user()
    image = await service.upload_image(owner, _FakeUpload("logo.png", "image/png", PNG_BYTES))

    with pytest.raises(HTTPException) as exc:
        await _create(service, other, "Stolen", html=f'<p>x</p><img src="cid:{image.content_id}">')
    assert exc.value.status_code == 400


async def test_multiple_images_in_one_signature_and_listing_urls():
    storage = _FakeStorage()
    service, _ = _service(storage=storage)
    user = _user()
    probe = await service.upload_image(user, _FakeUpload("probe.png", "image/png", PNG_BYTES))
    partner = await service.upload_image(user, _FakeUpload("partner.png", "image/png", PNG_BYTES))

    created = await _create(
        service,
        user,
        "Two logos",
        html=(
            "<p>Regards,<br>Hari Krishna<br>Account Manager</p>"
            f'<p><img src="cid:{probe.content_id}" width="120"> '
            f'<img src="cid:{partner.content_id}" width="120"></p>'
        ),
    )

    assert f"cid:{probe.content_id}" in created.html
    assert f"cid:{partner.content_id}" in created.html
    listing = await service.list_signatures(user)
    assert set(listing.image_urls) == {probe.content_id, partner.content_id}


async def test_image_upload_validates_and_stores_under_signature_prefix():
    storage = _FakeStorage()
    service, repo = _service(storage=storage)
    user = _user()

    image = await service.upload_image(user, _FakeUpload("logo.png", "image/png", PNG_BYTES))

    assert image.content_id == signature_image_content_id(image.image_id)
    assert image.content_id.startswith("sigimg-") and len(image.content_id) == 39
    stored_key = repo.images[0].storage_key
    assert stored_key.startswith(f"{SIGNATURE_IMAGE_KEY_PREFIX}{user.user_id}/")
    assert image.preview_url


@pytest.mark.parametrize(
    "filename,content_type,extra_bytes,status",
    [
        ("logo.svg", "image/svg+xml", 0, 415),
        ("doc.pdf", "application/pdf", 0, 415),
        ("big.png", "image/png", 1024 * 1024, 413),
        ("empty.png", "image/png", -1, 400),
    ],
    ids=["svg", "pdf", "oversized", "empty"],
)
async def test_image_upload_rejects_unsafe_or_oversized_files(filename, content_type, extra_bytes, status):
    data = b"" if extra_bytes < 0 else PNG_BYTES + b"\x00" * extra_bytes
    service, repo = _service(storage=_FakeStorage())
    with pytest.raises(HTTPException) as exc:
        await service.upload_image(_user(), _FakeUpload(filename, content_type, data))
    assert exc.value.status_code == status
    assert repo.images == []


async def test_image_cleanup_keeps_images_still_referenced():
    storage = _FakeStorage()
    service, repo = _service(storage=storage)
    user = _user()
    shared = await service.upload_image(user, _FakeUpload("shared.png", "image/png", PNG_BYTES))
    sent = await service.upload_image(user, _FakeUpload("sent.png", "image/png", PNG_BYTES))
    drafted = await service.upload_image(user, _FakeUpload("draft.png", "image/png", PNG_BYTES))
    orphan = await service.upload_image(user, _FakeUpload("orphan.png", "image/png", PNG_BYTES))
    old = datetime.now(timezone.utc) - timedelta(days=2)
    for image in repo.images:
        image.created_at = old

    html = f'<p>x</p><img src="cid:{shared.content_id}">'
    a = await _create(service, user, "A", html=html)
    b = await _create(service, user, "B", html=html)
    by_id = {i.image_id: i for i in repo.images}
    repo.attachment_keys.add(by_id[sent.image_id].storage_key)
    repo.draft_content_ids[user.user_id] = {drafted.content_id}

    # Deleting one of two signatures sharing an image keeps the image.
    await service.delete_signature(user, a.signature_id)

    remaining = {i.image_id for i in repo.images}
    assert shared.image_id in remaining
    assert sent.image_id in remaining  # a sent message still points at it
    assert drafted.image_id in remaining  # an unsent draft still uses it
    assert orphan.image_id not in remaining
    assert storage.deleted == [by_id[orphan.image_id].storage_key]

    await service.delete_signature(user, b.signature_id)
    assert shared.image_id not in {i.image_id for i in repo.images}


async def test_freshly_uploaded_unreferenced_image_is_not_swept():
    storage = _FakeStorage()
    service, repo = _service(storage=storage)
    user = _user()
    sig = await _create(service, user, "A")
    await service.upload_image(user, _FakeUpload("new.png", "image/png", PNG_BYTES))

    await service.update_signature(user, sig.signature_id, EmailSignatureUpdate(name="B"))

    assert len(repo.images) == 1
    assert storage.deleted == []


# ---------------- legacy migration ----------------


def _load_migration():
    path = (
        Path(__file__).resolve().parent.parent
        / "alembic_rbac"
        / "versions"
        / "a7c9e1b3d5f8_add_email_signatures.py"
    )
    spec = importlib.util.spec_from_file_location("sig_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_legacy_migration_preserves_existing_signature_with_logo():
    migration = _load_migration()
    keep = SimpleNamespace(user_id=uuid4(), signature_html="<div>Regards,<br>Kamal</div>")
    blank = SimpleNamespace(user_id=uuid4(), signature_html="   ")

    rows = migration.build_backfill_rows([keep, blank])

    assert len(rows) == 1
    _signature_id, user_id, html = rows[0]
    assert user_id == str(keep.user_id)
    # Byte-identical to what the composer combined before, and to the
    # service's own fallback for a user who has no rows.
    assert html == legacy_signature_with_logo(keep.signature_html)
    assert migration.COMPANY_LOGO_BLOCK_HTML == COMPANY_LOGO_BLOCK_HTML
    assert migration.down_revision == "f2a4c6e8b0d3"
