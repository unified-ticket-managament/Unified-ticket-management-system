from uuid import UUID

from pydantic import BaseModel, EmailStr, Field

from app.rbac.schemas.common import ORMBase


# --------------------------------------------------
# Base Schema
# --------------------------------------------------


class CategoryBase(BaseModel):
    # Categories are created dynamically at runtime (no fixed Python
    # enum backing this anymore — see shared_models.models.Category) —
    # trimming/blank/duplicate checks happen in CategoryService, since
    # a duplicate check needs a DB round trip Pydantic can't do here.
    category_name: str = Field(min_length=1, max_length=150)
    # This category's own CATEGORY shared inbox address (e.g.
    # apm@company.com) — optional, mirrors Client.inbox_email. Cross-
    # table uniqueness against Client.inbox_email and normalization
    # (strip/lowercase) both happen in CategoryService, not here.
    inbox_email: EmailStr | None = Field(default=None)


# --------------------------------------------------
# Create Category
# --------------------------------------------------


class CategoryCreate(CategoryBase):
    # Staff/Team Lead users to associate with this category at
    # creation time — entirely optional (a category may be created
    # with zero, some, or many users; there is no "at least one"
    # requirement). Reuses the existing user_categories many-to-many
    # membership mechanism (see UserRepository.add_users_to_category)
    # rather than a second relationship.
    user_ids: list[UUID] = Field(default_factory=list)


# --------------------------------------------------
# Update Category
# --------------------------------------------------


class CategoryUpdate(BaseModel):
    category_name: str | None = Field(default=None, min_length=1, max_length=150)
    inbox_email: EmailStr | None = Field(default=None)


# --------------------------------------------------
# Category Response
# --------------------------------------------------


class CategoryResponse(ORMBase):
    category_id: UUID
    category_name: str
    inbox_email: str | None = None
    # Live count of users holding this category via user_categories,
    # plus any Account Manager(s) Reporting-Manager-mapped to it via
    # reporting_manager_teams — populated by CategoryService (batch
    # query, not per-row), 0 when not computed by a given caller.
    # Purely for display (the Category Management UI's "Assigned
    # Users" column).
    assigned_user_count: int = 0


# --------------------------------------------------
# Category List Response
# --------------------------------------------------

class CategoryListResponse(BaseModel):
    categories: list[CategoryResponse]
    total: int


# --------------------------------------------------
# Category Members (Edit Category — add/remove Team Leads/Staff)
# --------------------------------------------------


class CategoryMemberResponse(BaseModel):
    user_id: UUID
    name: str
    email: str
    # The member's actual role name ("Team Lead"/"Staff"/...) — lets
    # the Edit Category UI bucket members into the same two pickers
    # the Create form already uses, without a second lookup.
    role_name: str


class CategoryMembersResponse(BaseModel):
    members: list[CategoryMemberResponse]


class CategoryMembersUpdate(BaseModel):
    # The complete new membership set for this category — a full
    # replace (add whoever's new, remove whoever's missing), same
    # semantics as UserService.set_user_categories but scoped to one
    # category instead of one user. Empty list is valid (removes
    # everyone).
    user_ids: list[UUID] = Field(default_factory=list)
