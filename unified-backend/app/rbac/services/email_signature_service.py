import logging
import re
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from bs4 import BeautifulSoup
from fastapi import HTTPException, UploadFile, status

from shared_models.models import User

from app.rbac.models.email_signature import EmailSignature, EmailSignatureImage
from app.rbac.repositories.email_signature_repository import EmailSignatureRepository
from app.rbac.repositories.user_repository import UserRepository
from app.rbac.schemas.email_signature import (
    EmailSignatureCreate,
    EmailSignatureImageResponse,
    EmailSignatureListResponse,
    EmailSignatureResponse,
    EmailSignatureUpdate,
)
from app.ticketing.services.attachment_service import is_previewable_image
from app.ticketing.services.company_signature_logo import COMPANY_LOGO_CONTENT_ID
from app.ticketing.services.signature_inline_images import (
    SIGNATURE_IMAGE_CONTENT_ID_PREFIX,
    SIGNATURE_IMAGE_KEY_PREFIX,
    referenced_signature_image_ids,
    signature_image_content_id,
)
from app.ticketing.storage.base import StorageService
from app.ticketing.utils.html_sanitizer import sanitize_outbound_html
from app.ticketing.utils.validators import (
    sanitize_filename,
    validate_attachment_magic_bytes,
    validate_attachment_type,
)

logger = logging.getLogger(__name__)

# A signature logo is small; this keeps every message carrying it well
# inside Graph's inline-attachment budget (see attachment_service.
# GRAPH_INLINE_ATTACHMENT_MAX_BYTES, 3MB per file).
SIGNATURE_IMAGE_MAX_BYTES = 1 * 1024 * 1024
MAX_SIGNATURES_PER_USER = 25

# An uploaded image that no signature references yet is only cleaned
# up after this long — long enough that an image uploaded into a
# signature still being edited (another tab, a slow save) is never
# swept out from under it.
UNREFERENCED_IMAGE_GRACE_PERIOD = timedelta(hours=24)

# Exactly what the composer has always appended after a user's own
# signature text (see the frontend's former richText.ts
# buildSignatureBlockHtml) — now carried as ordinary signature content
# instead of being hard-coded for everyone. Used for the legacy
# fallback below; the migration that introduced email_signatures
# backfills the identical block (alembic_rbac a7c9e1b3d5f8).
COMPANY_LOGO_BLOCK_HTML = (
    f'<div><img src="cid:{COMPANY_LOGO_CONTENT_ID}" alt="Probe Practice Solutions" width="150"></div>'
)

_SIGNATURE_IMAGE_SRC = re.compile(
    rf"^cid:{SIGNATURE_IMAGE_CONTENT_ID_PREFIX}([0-9a-f]{{32}})$",
    re.IGNORECASE,
)


def legacy_signature_with_logo(signature_html: str | None) -> str | None:
    """
    A pre-multi-signature user's composer signature: their own
    users.signature_html followed by the company logo, exactly as the
    composer used to stitch them together. None when they have none.
    """

    if not signature_html or not signature_html.strip():
        return None
    return f"{signature_html}{COMPANY_LOGO_BLOCK_HTML}"


class EmailSignatureService:
    """
    Self-service management of the effective user's own email
    signatures. Every method takes the request's authenticated
    `current_user` — which, under impersonation, is already the
    impersonated user (app/dependencies/auth.py puts the actor on
    `impersonator_id`, never `user_id`) — and only ever reads or writes
    rows owned by `current_user.user_id`. There is no user-id parameter
    anywhere, so no caller can reach another account's signatures.
    """

    def __init__(
        self,
        signature_repository: EmailSignatureRepository,
        user_repository: UserRepository,
        storage_service: StorageService | None = None,
    ):
        self.signature_repository = signature_repository
        self.user_repository = user_repository
        self.storage_service = storage_service

    # --------------------------------------------------
    # Read
    # --------------------------------------------------

    async def list_signatures(self, current_user: User) -> EmailSignatureListResponse:
        user_id = current_user.user_id
        signatures = await self.signature_repository.list_for_user(user_id)

        fallback_html = None
        if not signatures:
            # current_user may be a transient JWT-reconstructed object
            # (RBAC cache hit) with no profile fields — re-read the row.
            persistent = await self.user_repository.get_by_id(user_id)
            fallback_html = legacy_signature_with_logo(
                persistent.signature_html if persistent is not None else None
            )

        return EmailSignatureListResponse(
            signatures=[EmailSignatureResponse.model_validate(s) for s in signatures],
            default_signature_id=next(
                (s.signature_id for s in signatures if s.is_default), None
            ),
            fallback_signature_html=fallback_html,
            image_urls=await self._image_urls(user_id, [s.html for s in signatures]),
        )

    async def _image_urls(self, user_id: UUID, html_values: list[str]) -> dict[str, str]:
        if self.storage_service is None:
            return {}

        image_ids: list[UUID] = []
        for html in html_values:
            for image_id in referenced_signature_image_ids(html):
                if image_id not in image_ids:
                    image_ids.append(image_id)

        urls: dict[str, str] = {}
        for image in await self.signature_repository.list_images_by_ids(user_id, image_ids):
            url = await self._preview_url(image)
            if url:
                urls[signature_image_content_id(image.image_id)] = url
        return urls

    async def _preview_url(self, image: EmailSignatureImage) -> str | None:
        if self.storage_service is None or not is_previewable_image(image.filename):
            return None
        try:
            return await self.storage_service.presigned_get_url(
                object_key=image.storage_key,
                filename=image.filename,
                inline=True,
            )
        except Exception:
            logger.warning("Could not presign signature image %s", image.image_id, exc_info=True)
            return None

    # --------------------------------------------------
    # Write
    # --------------------------------------------------

    async def create_signature(
        self, current_user: User, data: EmailSignatureCreate
    ) -> EmailSignatureResponse:
        user_id = current_user.user_id
        await self.signature_repository.lock_user(user_id)

        existing = await self.signature_repository.list_for_user(user_id)
        if len(existing) >= MAX_SIGNATURES_PER_USER:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"You can save at most {MAX_SIGNATURES_PER_USER} signatures.",
            )
        self._ensure_unique_name(existing, data.name)

        html = await self.sanitize_signature_html(user_id, data.html)

        # A user's first signature is always their default; a later one
        # only when they explicitly ask — never silently replaces it.
        make_default = data.is_default or not existing
        if make_default:
            await self.signature_repository.clear_default(user_id)

        signature = await self.signature_repository.add(
            EmailSignature(
                user_id=user_id,
                name=data.name,
                html=html,
                is_default=make_default,
            )
        )
        return EmailSignatureResponse.model_validate(signature)

    async def update_signature(
        self, current_user: User, signature_id: UUID, data: EmailSignatureUpdate
    ) -> EmailSignatureResponse:
        user_id = current_user.user_id
        await self.signature_repository.lock_user(user_id)
        signature = await self._get_owned_or_404(user_id, signature_id)

        if data.name is not None and data.name != signature.name:
            existing = await self.signature_repository.list_for_user(user_id)
            self._ensure_unique_name(
                [s for s in existing if s.signature_id != signature_id], data.name
            )
            signature.name = data.name

        if data.html is not None:
            signature.html = await self.sanitize_signature_html(user_id, data.html)

        signature.updated_at = datetime.now(timezone.utc)
        await self.signature_repository.save(signature)
        await self._cleanup_unreferenced_images(user_id)
        return EmailSignatureResponse.model_validate(signature)

    async def delete_signature(self, current_user: User, signature_id: UUID) -> None:
        """
        Deleting the default promotes the oldest remaining signature (the
        first one in the user's list) so there is always a default while
        any signature exists; deleting the last one leaves none, and the
        composer falls back to the legacy default (see list_signatures).
        Previously sent mail is unaffected — it carries its own copy.
        """

        user_id = current_user.user_id
        await self.signature_repository.lock_user(user_id)
        signature = await self._get_owned_or_404(user_id, signature_id)
        was_default = signature.is_default

        await self.signature_repository.delete(signature)

        if was_default:
            remaining = await self.signature_repository.list_for_user(user_id)
            if remaining:
                remaining[0].is_default = True
                await self.signature_repository.save(remaining[0])

        await self._cleanup_unreferenced_images(user_id)

    async def set_default(self, current_user: User, signature_id: UUID) -> EmailSignatureResponse:
        user_id = current_user.user_id
        await self.signature_repository.lock_user(user_id)
        signature = await self._get_owned_or_404(user_id, signature_id)

        if not signature.is_default:
            await self.signature_repository.clear_default(user_id)
            signature.is_default = True
            await self.signature_repository.save(signature)

        return EmailSignatureResponse.model_validate(signature)

    # --------------------------------------------------
    # Images
    # --------------------------------------------------

    async def upload_image(
        self, current_user: User, file: UploadFile
    ) -> EmailSignatureImageResponse:
        if self.storage_service is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Attachment storage is not configured.",
            )

        filename = sanitize_filename(file.filename or "image")
        try:
            extension = validate_attachment_type(filename, file.content_type)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail=str(exc)
            )

        # is_previewable_image is the same extension allow-list every
        # inline preview uses — SVG is excluded there on purpose (a
        # scriptable format), and stays excluded here.
        if not is_previewable_image(filename) or not (file.content_type or "").startswith(
            "image/"
        ):
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail="Signature images must be PNG, JPEG, GIF, BMP or WebP files.",
            )

        data = await file.read()
        if not data:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="The image file is empty."
            )
        if len(data) > SIGNATURE_IMAGE_MAX_BYTES:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=(
                    f'"{filename}" exceeds the '
                    f"{SIGNATURE_IMAGE_MAX_BYTES // (1024 * 1024)}MB signature-image limit."
                ),
            )

        try:
            validate_attachment_magic_bytes(filename, extension, data)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail=str(exc)
            )

        image_id = uuid4()
        object_key = f"{SIGNATURE_IMAGE_KEY_PREFIX}{current_user.user_id}/{image_id}-{filename}"
        await self.storage_service.upload(
            data=data, object_key=object_key, content_type=file.content_type
        )

        image = await self.signature_repository.add_image(
            EmailSignatureImage(
                image_id=image_id,
                user_id=current_user.user_id,
                filename=filename,
                mime_type=file.content_type,
                size_bytes=len(data),
                storage_key=object_key,
                bucket_name=getattr(self.storage_service, "bucket", None),
            )
        )

        return EmailSignatureImageResponse(
            image_id=image.image_id,
            content_id=signature_image_content_id(image.image_id),
            filename=image.filename,
            mime_type=image.mime_type,
            size_bytes=image.size_bytes,
            preview_url=await self._preview_url(image),
        )

    async def _cleanup_unreferenced_images(self, user_id: UUID) -> None:
        """
        Best-effort removal of this user's images that no signature,
        no unsent draft and no sent message references any more. An
        image any sent message used is kept for good: that message's
        inline Attachment row shares this image's storage object (see
        signature_inline_images.py), and the app's own Sent view still
        renders from it. Never fails the request that triggered it.
        """

        if self.storage_service is None:
            return

        try:
            referenced = set()
            for signature in await self.signature_repository.list_for_user(user_id):
                referenced.update(referenced_signature_image_ids(signature.html))

            cutoff = datetime.now(timezone.utc) - UNREFERENCED_IMAGE_GRACE_PERIOD
            candidates = await self.signature_repository.list_images_created_before(
                user_id, cutoff
            )
            for image in candidates:
                if image.image_id in referenced:
                    continue
                if await self.signature_repository.is_storage_key_used_by_attachment(
                    image.storage_key
                ):
                    continue
                if await self.signature_repository.is_content_id_in_user_drafts(
                    user_id, signature_image_content_id(image.image_id)
                ):
                    continue
                await self.storage_service.delete(object_key=image.storage_key)
                await self.signature_repository.delete_image(image)
        except Exception:
            logger.warning(
                "Signature image cleanup failed for user %s", user_id, exc_info=True
            )

    # --------------------------------------------------
    # Helpers
    # --------------------------------------------------

    async def sanitize_signature_html(self, user_id: UUID, html: str) -> str:
        """
        Every signature passes through the exact same outbound sanitizer
        as a message body (no scripts, event handlers, javascript: URLs,
        iframes/objects, unsafe CSS, remote images). On top of that,
        every <img> must be a `cid:` reference to either the system
        company logo or one of this user's own uploaded signature
        images — checked against the raw input first, so a stray remote
        or preview URL is a clear 400 instead of the sanitizer silently
        dropping the image.
        """

        soup = BeautifulSoup(html, "html.parser")
        image_ids: list[UUID] = []
        for img in soup.find_all("img"):
            src = (img.get("src") or "").strip()
            if src.lower() == f"cid:{COMPANY_LOGO_CONTENT_ID}":
                continue
            match = _SIGNATURE_IMAGE_SRC.match(src)
            if match is None:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Signature images must be uploaded from the signature editor.",
                )
            image_ids.append(UUID(hex=match.group(1).lower()))

        if image_ids:
            owned = {
                image.image_id
                for image in await self.signature_repository.list_images_by_ids(
                    user_id, image_ids
                )
            }
            if any(image_id not in owned for image_id in image_ids):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="A signature image could not be found. Please upload it again.",
                )

        sanitized = sanitize_outbound_html(html)
        has_text = BeautifulSoup(sanitized, "html.parser").get_text().strip() != ""
        if not has_text and "<img" not in sanitized.lower():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Signature content cannot be empty.",
            )
        return sanitized

    async def _get_owned_or_404(self, user_id: UUID, signature_id: UUID) -> EmailSignature:
        signature = await self.signature_repository.get_for_user(user_id, signature_id)
        if signature is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Signature not found."
            )
        return signature

    @staticmethod
    def _ensure_unique_name(others: list[EmailSignature], name: str) -> None:
        if any(s.name.strip().lower() == name.strip().lower() for s in others):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f'You already have a signature named "{name}".',
            )
