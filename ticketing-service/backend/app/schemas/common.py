from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

#schemas/common.py
class ORMBase(BaseModel):
    """
    Base schema for reading SQLAlchemy ORM objects.
    """

    model_config = ConfigDict(from_attributes=True)


class TimestampResponse(BaseModel):
    """
    Common timestamp fields used in response schemas.
    """

    created_at: datetime
    updated_at: datetime


class UUIDResponse(BaseModel):
    """
    Common UUID field pattern.
    """

    id: UUID