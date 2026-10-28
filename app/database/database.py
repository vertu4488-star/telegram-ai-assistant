"""Database engine and session management using async SQLAlchemy."""

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import settings
from app.database.models import Base, PublishedNews  # noqa: F401 - register news table before create_all

logger = logging.getLogger(__name__)

# Global engine and sessionmaker instances
_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def get_engine(database_url: str | None = None) -> AsyncEngine:
    """Get or create the async engine."""
    global _engine
    if _engine is None:
        url = database_url or settings.DATABASE_URL
        _engine = create_async_engine(
            url,
            echo=False,
            future=True,
        )
    return _engine


def get_sessionmaker(engine: AsyncEngine | None = None) -> async_sessionmaker[AsyncSession]:
    """Get or create the async session factory."""
    global _sessionmaker
    if _sessionmaker is None:
        eng = engine or get_engine()
        _sessionmaker = async_sessionmaker(
            bind=eng,
            class_=AsyncSession,
            expire_on_commit=False,
        )
    return _sessionmaker


async def init_db(database_url: str | None = None) -> None:
    """Initialize database tables automatically if they do not exist."""
    eng = get_engine(database_url)
    logger.info("Initializing database tables...")
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database tables initialized successfully.")


async def close_db() -> None:
    """Dispose of engine connections during application shutdown."""
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _sessionmaker = None
        logger.info("Database connections closed.")


@asynccontextmanager
async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Provide an async session with automatic commit / rollback context."""
    factory = get_sessionmaker()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
