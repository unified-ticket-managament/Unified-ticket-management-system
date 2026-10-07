from datetime import datetime
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator


class MailReminderCreate(BaseModel):
    """
    No user_id field on purpose: ownership always comes from the
    authenticated user, never the request body. `remind_at` must carry
    a UTC offset (naive datetimes are rejected with a 422).
    """

    interaction_id: UUID
    remind_at: AwareDatetime


class MailReminderUpdate(BaseModel):
    remind_at: AwareDatetime


class MailReminderSnooze(BaseModel):
    """Either an absolute `remind_at` or a relative `minutes` — exactly one."""

    remind_at: AwareDatetime | None = None
    minutes: int | None = Field(default=None, ge=1, le=60 * 24 * 365)

    @model_validator(mode="after")
    def _exactly_one(self):
        if (self.remind_at is None) == (self.minutes is None):
            raise ValueError("Provide exactly one of remind_at or minutes.")
        return self


class MailReminderResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    reminder_id: UUID
    interaction_id: UUID
    remind_at: datetime
    status: str
    snooze_count: int
    fired_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
