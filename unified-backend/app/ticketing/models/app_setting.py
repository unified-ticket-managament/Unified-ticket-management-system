import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import DateTime, String, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from shared_models.database import Base


class AppSetting(Base):
    """
    One row per runtime application setting an administrator can change
    from the Settings UI (key -> JSON value). A MISSING row means "use the
    documented default" — for every setting here that default is the safe
    one (e.g. Read Receipts: OFF), so a fresh database, or one where the
    row was never written, can never have an unapproved feature enabled.

    Deliberately tiny: this is not a general configuration framework, it
    is the smallest persistence the Read Receipts toggle needs. Add a new
    key by adding a constant and a typed accessor in
    app_settings_service.py, never by reading arbitrary keys from a
    request.
    """

    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)

    value: Mapped[Any] = mapped_column(JSONB, nullable=False)

    # Who last changed it (bare UUID, no FK — users live in the RBAC
    # migration chain, same convention as scope_ticket_id elsewhere).
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=text("now()"),
        nullable=False,
    )
