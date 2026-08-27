import uuid
from datetime import datetime, timezone

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Index, String, Text, text
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

    # Composite, not table-wide: see content_id's own comment below for
    # why. `postgresql_where` keeps NULL content_id (every ordinary,
    # non-inline attachment) out of the index entirely, matching the
    # original table-wide index's own partial-index behavior.
    __table_args__ = (
        Index(
            "ix_attachments_content_id",
            "interaction_id",
            "content_id",
            unique=True,
            postgresql_where=text("content_id IS NOT NULL"),
        ),
    )

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

    # Set for an inline image, two different ways depending on origin:
    # a pasted-into-the-composer screenshot gets a short,
    # server-generated token (AttachmentService.create_inline_image),
    # cross-referenced back to this row at send time
    # (email_envelope.py/graph_client.py); an inbound Graph message's
    # own inline image instead carries Graph's own `contentId` value
    # UNCHANGED (mail_mapping_service.build_upload_files_from_graph_
    # attachments) — required so the stored body's own
    # `cid:{contentId}` reference still resolves. NULL for every
    # ordinary attachment, including a real photo a user deliberately
    # attaches as a downloadable file rather than pasting/embedding
    # inline.
    #
    # Only unique *within one interaction* (see ix_attachments_
    # content_id below) — a `cid:` reference only ever needs to
    # resolve unambiguously inside its own message's body. It is NOT
    # globally unique: Graph/Outlook legitimately reuses the exact
    # same contentId for the same inline image (typically a signature/
    # logo) across many unrelated messages from the same sender — this
    # used to collide against a table-wide unique index, which
    # (because the resulting IntegrityError was never caught) silently
    # dropped the entire inbound email, not just its attachment.
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

    # Phase 2 hardening: was "pending", implying an antivirus scan is
    # in progress/will happen — none exists anywhere in this codebase
    # (grep confirms nothing ever updates or reads this column beyond
    # this default). "not_scanned" is a static, honest value; no AV
    # scanning is added by this change — malware/AV scanning is
    # explicitly out of scope. See the accompanying migration for the
    # one-time backfill of already-inserted "pending" rows.
    scan_status: Mapped[str] = mapped_column(
        String(20),
        default="not_scanned",
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