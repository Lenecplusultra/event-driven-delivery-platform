"""
services/order-service/app/core/dependencies.py

FastAPI dependency injection providers for Order Service.

Centralizing dependencies here means route handlers never import
session factories or settings directly — only through Depends().
"""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from libs.common.db.session import get_session_factory

# ── DB session dependency ─────────────────────────────────────────────────────


def get_db_factory() -> async_sessionmaker[AsyncSession]:
    """Return the session factory (used by readiness probe and consumers)."""
    return get_session_factory()


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI dependency that yields one AsyncSession per request.
    Commits on success, rolls back on exception.
    """
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
