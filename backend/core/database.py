from contextlib import asynccontextmanager
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from core.config import settings

# pool_pre_ping is intentionally DISABLED for asyncpg.
# SQLAlchemy's synchronous do_ping() calls dbapi_connection.ping() which internally
# calls await_() outside a greenlet context → MissingGreenlet crash (sqlalche.me/e/20/xd2s).
# Mitigation: pool_recycle evicts stale connections proactively; asyncpg reconnects
# automatically on the next acquire if the connection is broken.
_ENGINE_KWARGS = dict(
    echo=settings.app_env == "development",
    pool_pre_ping=False,       # ← MissingGreenlet fix
    pool_recycle=1800,         # recycle connections idle for > 30 min
    pool_use_lifo=True,        # prefer warm recently-used connections
    pool_size=10,
    max_overflow=20,
)

# Global engine for standard FastAPI requests (created when module is imported)
engine = create_async_engine(settings.database_url, **_ENGINE_KWARGS)

AsyncSessionLocal = async_sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


@asynccontextmanager
async def get_db_context() -> AsyncSession:
    """Async context manager version of get_db for use in non-dependency code."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


def get_async_sessionmaker() -> async_sessionmaker[AsyncSession]:
    """
    Creates a fresh engine and sessionmaker.
    CRITICAL for Celery tasks running asyncio.run(), which create a separate
    event loop per task execution. Reusing the global `engine` results in
    'Future attached to a different loop' asyncpg/asyncio errors.
    """
    fresh_engine = create_async_engine(settings.database_url, **_ENGINE_KWARGS)
    return async_sessionmaker(
        fresh_engine, class_=AsyncSession, expire_on_commit=False
    )
