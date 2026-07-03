from sqlalchemy.ext.asyncio import AsyncSession


class BaseRepository:
    """
    Base repository class.

    Every repository inherits from this class
    to access the database session.
    """

    def __init__(self, db: AsyncSession):
        self.db = db