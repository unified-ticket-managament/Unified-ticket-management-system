from uuid import UUID

from pydantic import BaseModel

from shared_models.models import CategoryName

from app.schemas.common import ORMBase


# --------------------------------------------------
# Base Schema
# --------------------------------------------------


class CategoryBase(BaseModel):
    category_name: CategoryName


# --------------------------------------------------
# Create Category
# --------------------------------------------------


class CategoryCreate(CategoryBase):
    pass


# --------------------------------------------------
# Update Category
# --------------------------------------------------


class CategoryUpdate(BaseModel):
    category_name: CategoryName | None = None


# --------------------------------------------------
# Category Response
# --------------------------------------------------


class CategoryResponse(ORMBase):
    category_id: UUID
    category_name: CategoryName


# --------------------------------------------------
# Category List Response
# --------------------------------------------------

class CategoryListResponse(BaseModel):
    categories: list[CategoryResponse]
    total: int
