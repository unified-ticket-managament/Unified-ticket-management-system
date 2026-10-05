import uuid
from datetime import datetime, timezone

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Index, String, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from shared_models.database import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class EmailSignature(Base):
    """
    One of a user's saved, named email signatures (Outlook-style "many
    signatures, one default"). Replaces the single, flat
    `users.signature_html` column as the composer's source of truth —
    that column is kept only as the legacy fallback for a user with no
    rows here at all (see EmailSignatureService.list_signatures), so a
    brand-new user (seeded there by UserService.create_user) or one who
    deleted every signature still composes with today's default.

    `html` is sanitized (sanitize_outbound_html) and image-validated
    before it is ever persisted — every <img> is a `cid:` reference to
    either one of this user's own EmailSignatureImage rows or the
    system company logo (see EmailSignatureService.sanitize_signature_html).
    It is copied into the composer at compose time, never rendered
    dynamically into an already-sent message, so editing or deleting a
    signature can never change mail that already went out.

    At most one row per user has `is_default = true`, enforced by the
    partial unique index below (not just in the service) — two
    concurrent "set as default" requests can't both win.
    """

    __tablename__ = "email_signatures"

    signature_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.user_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    name: Mapped[str] = mapped_column(String(100), nullable=False)

    html: Mapped[str] = mapped_column(Text, nullable=False)

    is_default: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default=text("false"),
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )

    __table_args__ = (
        Index(
            "uq_email_signatures_one_default_per_user",
            "user_id",
            unique=True,
            postgresql_where=text("is_default"),
        ),
    )


class EmailSignatureImage(Base):
    """
    An image (logo, badge, divider) uploaded for use inside a user's
    signatures, referenced from EmailSignature.html as
    `cid:sigimg-<image_id hex>` — see app/ticketing/services/
    signature_inline_images.py for how that becomes a true inline MIME
    part (Content-ID + inline disposition) at send time.

    Immutable once uploaded: replacing a logo uploads a new row rather
    than overwriting this one, which is what makes a stable,
    per-image Content-ID safe to reuse across messages (the same cid
    always means the same bytes). One row can be referenced by any
    number of the same user's signatures — no per-signature copy.

    Stored under the `signature-images/` object-key prefix. Every sent
    message that used the image gets its own inline Attachment row
    pointing at this same `storage_key` (no byte copy per email), so
    the attachment-deletion paths skip deleting objects under that
    prefix, and EmailSignatureService only ever removes an image's
    object once no signature and no Attachment row references it.
    """

    __tablename__ = "email_signature_images"

    image_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.user_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    filename: Mapped[str] = mapped_column(String(255), nullable=False)

    mime_type: Mapped[str] = mapped_column(String(100), nullable=False)

    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)

    storage_key: Mapped[str] = mapped_column(Text, nullable=False, unique=True)

    bucket_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )
