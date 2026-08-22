import uuid
from datetime import datetime, timezone

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from shared_models.database import Base

from typing import TYPE_CHECKING
#attachment.py
if TYPE_CHECKING:
    from .interaction import Interaction


class Attachment(Base):
    """
    Attachment Model
    """

    __tablename__ = "attachments"

    attachment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    interaction_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("interactions.interaction_id"),
        nullable=False,
    )

    filename: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    mime_type: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    size_bytes: Mapped[int | None] = mapped_column(
        BigInteger,
        nullable=True,
    )

    # Nullable because an external-link attachment (see
    # is_external_link below) has no real file bytes to store — the
    # only thing we ever have for one is the URL itself.
    storage_key: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    bucket_name: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    # OneDrive/SharePoint "Attach as cloud link" files: Outlook creates
    # no real Graph attachment object for these at all (confirmed
    # live — hasAttachments comes back False, the attachments
    # collection is empty), only an <a> anchor embedded in the message
    # body. external_url carries that anchor's href; storage_key/
    # bucket_name stay NULL since there are no bytes we ever fetch or
    # store. See mail_mapping_service.extract_cloud_link_attachments.
    external_url: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    is_external_link: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    # Only set for an attachment explicitly uploaded as a pasted
    # inline image (see AttachmentService.create_inline_image) — a
    # short, server-generated token embedded as `cid:<content_id>` in
    # the composer's HTML body and cross-referenced back to this exact
    # row at send time (see email_envelope.py/graph_client.py). NULL
    # for every ordinary attachment, including a real photo a user
    # deliberately attaches as a downloadable file rather than pasting
    # inline. Never client-supplied — minted server-side to avoid one
    # upload spoofing/colliding with another's cid: reference.
    content_id: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )

    # True only for the inline-pasted-image case above; False
    # (default) for every other attachment, including images attached
    # as ordinary downloadable files. Distinct from is_external_link —
    # an inline image always has real stored bytes.
    is_inline: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    scan_status: Mapped[str] = mapped_column(
        String(20),
        default="pending",
        nullable=False,
    )

    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=True,
    )

    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=True,
    )

    interaction: Mapped["Interaction"] = relationship(
        "Interaction",
        back_populates="attachments",
    )