"""
libs/common/db/session.py

Async SQLAlchemy session factory shared across services.

Each service creates its own engine by passing its DATABASE_URL.
The session is used via FastAPI dependency injection or as an
async context manager in consumers.

Usage (FastAPI dependency):
    from libs.common.db.session import get_async_session

    @router.post("/orders")
    async def create_order(
        db: AsyncSession = Depends(get_async_session),
    ):
        ...

Usage (consumer / background task):
    async with async_session_factory() as session:
        async with session.begin():
            await repo.save(order, session)
"""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

# ── ORM base shared by all services ──────────────────────────────────────────


class Base(DeclarativeBase):
    """SQLAlchemy declarative base. All service models inherit from this."""
    pass


# ── Engine and session factory ────────────────────────────────────────────────
# Each service instantiates these in its own db/session.py using its DATABASE_URL.

_async_session_factory: async_sessionmaker[AsyncSession] | None = None


def init_db(database_url: str) -> None:
    """
    Call once at application startup with the service's DATABASE_URL.
    Uses asyncpg driver: postgresql+asyncpg://user:pass@host/db
    """
    global _async_session_factory

    engine = create_async_engine(
        database_url,
        echo=False,
        pool_size=10,
        max_overflow=20,
        pool_pre_ping=True,
    )
    _async_session_factory = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    if _async_session_factory is None:
        raise RuntimeError("Database not initialized. Call init_db() at startup.")
    return _async_session_factory


async def get_async_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency that yields a database session per request."""
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
