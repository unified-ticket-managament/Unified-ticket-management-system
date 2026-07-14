from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import get_settings
from app.database.timing import register_db_timing


settings = get_settings()

engine = create_async_engine(
    settings.database_url,
    echo=settings.debug,
    pool_pre_ping=True,
    # DATABASE_URL points at Neon's pooled (PgBouncer) endpoint
    # (hostname contains "-pooler"), which itself fronts a much smaller
    # number of real Postgres backend connections — this app-level pool
    # is a second, independent limit on top of that, not a duplicate of
    # it. Raised from 10/20 (30 total) after a frontend request-
    # duplication bug was found flooding this app with 200-300
    # concurrent requests at once, which queued for a free connection
    # near SQLAlchemy's default 30s pool_timeout — explaining "26-48s"
    # responses on trivially cheap queries (e.g. a 3-row SLA policy
    # list) that could never really take that long to execute. The
    # frontend bug is now fixed, so this is headroom against future
    # bursts rather than the primary fix; pool_timeout is set explicitly
    # (shorter than the previous implicit 30s default) so a genuine
    # overload fails fast with a clear error instead of a request
    # hanging near the old default.
    pool_size=20,
    max_overflow=30,
    pool_timeout=10,
    pool_recycle=1800,
)

# Backs the `db` phase of the Server-Timing header (app/main.py) —
# see app/database/timing.py for why this needs a ContextVar rather
# than a plain accumulator.
register_db_timing(engine)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()

        except Exception:
            await session.rollback()
            raise

    
