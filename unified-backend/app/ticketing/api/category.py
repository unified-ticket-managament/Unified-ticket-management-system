from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from shared_models.models import User

from app.database.session import get_db
from app.dependencies.auth import get_current_user
from app.ticketing.repositories.category_repository import CategoryRepository
from app.ticketing.schemas.category import CategoryResponse

router = APIRouter(
    prefix="/categories",
    tags=["Categories"],
)


@router.get(
    "",
    response_model=list[CategoryResponse],
)
async def list_categories(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Every work-specialization category — populates the ticket-creation
    category dropdown in the Account Manager's inbox.
    """

    repository = CategoryRepository(db)

    return await repository.list_all()
