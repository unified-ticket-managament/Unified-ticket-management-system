from pydantic import BaseModel, ConfigDict


class ORMBase(BaseModel):
    """
    Base schema for all response models.
    Enables SQLAlchemy ORM -> Pydantic conversion.
    """

    model_config = ConfigDict(from_attributes=True)


class MessageResponse(BaseModel):
    """
    Generic success response.
    """

    message: str


class Pagination(BaseModel):
    """
    Pagination metadata.
    """

    total: int
    page: int
    page_size: int
    total_pages: int