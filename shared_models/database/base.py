from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """
    Base class for all SQLAlchemy ORM models.

    Every shared model (User) and every service-specific model
    (Ticket, Interaction, Attachment) will inherit from this Base.
    """

    pass