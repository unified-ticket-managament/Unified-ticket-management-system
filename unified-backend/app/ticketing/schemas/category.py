from uuid import UUID

from pydantic import BaseModel


class CategoryResponse(BaseModel):
    """
    A work-specialization category (Eligibility, AR, Claims, ...) —
    owned by the RBAC service (shared_models.models.Category), read
    here only to populate the ticket-creation category dropdown.
    """

    category_id: UUID
    category_name: str
