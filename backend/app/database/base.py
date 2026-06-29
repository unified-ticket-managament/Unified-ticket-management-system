"""
Shared SQLAlchemy Base.

This project does not define its own Declarative Base.
Instead, it uses the shared Base provided by the
shared-models package so that all services
(RBAC, Ticket Management, etc.) share the same metadata.
"""

from shared_models.database import Base

__all__ = ["Base"]