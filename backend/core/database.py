from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from core.config import settings

# Global engine for standard FastAPI requests (created when module is imported)
engine = create_async_engine(
    settings.database_url,
    echo=settings.app_env == "development",
    pool_pre_ping=True,
)

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


def get_async_sessionmaker() -> async_sessionmaker[AsyncSession]:
    """
    Creates a fresh engine and sessionmaker.
    CRITICAL for Celery tasks running asyncio.run(), which create a separate
    event loop per task execution. Reusing the global `engine` results in
    'Future attached to a different loop' asyncpg/asyncio errors.
    """
    fresh_engine = create_async_engine(
        settings.database_url,
        echo=settings.app_env == "development",
        pool_pre_ping=True,
    )
    return async_sessionmaker(
        fresh_engine, class_=AsyncSession, expire_on_commit=False
    )
