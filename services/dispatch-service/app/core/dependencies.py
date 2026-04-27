"""
services/dispatch-service/app/core/dependencies.py
"""

from collections.abc import AsyncGenerator

import redis.asyncio as aioredis
from sqlalchemy.ext.asyncio import AsyncSession

from libs.common.db.session import get_session_factory

_redis_client: aioredis.Redis | None = None


def set_redis_client(client: aioredis.Redis) -> None:
    global _redis_client
    _redis_client = client


def get_redis_client() -> aioredis.Redis:
    if _redis_client is None:
        raise RuntimeError("Redis not initialized")
    return _redis_client


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
