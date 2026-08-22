# distribution_list.py
#
# Schemas for the Distribution List (internal group) admin CRUD
# surface and for the shared "list active Distribution Lists for
# recipient selection" endpoint every recipient picker (Forward,
# Compose, Reply, Ticket Reply, Internal Note, Rules' forward_to)
# fetches from — see app/ticketing/api/distribution_list.py.

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.ticketing.schemas.common import ORMBase


class DistributionListMemberSummary(BaseModel):
    user_id: UUID
    name: str
    email: str


class DistributionListCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=1000)
    # At least one active internal user must be selected when creating
    # a group — an empty group is never allowed to exist, even
    # momentarily.
    member_user_ids: list[UUID] = Field(..., min_length=1)


class DistributionListUpdate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=1000)
    is_active: bool


class DistributionListActiveUpdate(BaseModel):
    is_active: bool


class DistributionListMemberAdd(BaseModel):
    user_id: UUID


class DistributionListSummaryResponse(ORMBase):
    """
    Admin list-view shape — no `members` array, just a count, so
    listing every Distribution List never triggers an N+1 members
    fetch.
    """

    distribution_list_id: UUID
    name: str
    description: str | None
    is_active: bool
    created_by: UUID | None
    member_count: int
    created_at: datetime
    updated_at: datetime


class DistributionListResponse(ORMBase):
    """Detail shape — returned by get/create/update/membership mutations."""

    distribution_list_id: UUID
    name: str
    description: str | None
    is_active: bool
    created_by: UUID | None
    created_at: datetime
    updated_at: datetime
    members: list[DistributionListMemberSummary] = Field(default_factory=list)


class DistributionListRecipientCandidate(BaseModel):
    """
    One row of the unscoped, authentication-only "active Distribution
    Lists for recipient selection" listing — deliberately not gated by
    rule:manage/rule:view_all (see the `active` route's own docstring).
    `member_count` is display context only ("Sales Team (8)") — the
    real send-time resolution always goes through
    DistributionListRepository.get_active_member_emails_by_list_ids,
    never this count.
    """

    distribution_list_id: UUID
    name: str
    description: str | None
    member_count: int


class DistributionListRecipientsResponse(BaseModel):
    distribution_lists: list[DistributionListRecipientCandidate]
