"""
services/dispatch-service/app/cache/driver_cache.py

Redis caching for driver availability.

Key design (from SPEC.md §10):
  driver:status:{driver_id}      TTL=30s   Single driver availability flag
  drivers:available:{zone}       TTL=10s   Set of available driver IDs in a zone

Short TTLs mean the cache is always near-fresh without explicit invalidation.
Cache failures are always non-fatal — fall back to DB.
"""

import json
import uuid

import redis.asyncio as aioredis

from libs.common.logging import get_logger

logger = get_logger(__name__)


class DriverCache:
    def __init__(self, redis_client: aioredis.Redis, status_ttl: int = 30, pool_ttl: int = 10):
        self._redis = redis_client
        self._status_ttl = status_ttl
        self._pool_ttl = pool_ttl

    def _status_key(self, driver_id: uuid.UUID) -> str:
        return f"driver:status:{driver_id}"

    def _pool_key(self, zone: str) -> str:
        return f"drivers:available:{zone}"

    async def get_available_drivers(self, zone: str) -> list[str] | None:
        """Return list of available driver_id strings, or None on miss."""
        try:
            raw = await self._redis.get(self._pool_key(zone))
            if raw:
                return json.loads(raw)
            return None
        except Exception as exc:
            logger.warning("Driver pool cache get failed", error=str(exc))
            return None

    async def set_available_drivers(self, zone: str, driver_ids: list[str]) -> None:
        try:
            await self._redis.setex(
                self._pool_key(zone),
                self._pool_ttl,
                json.dumps(driver_ids),
            )
        except Exception as exc:
            logger.warning("Driver pool cache set failed", error=str(exc))

    async def set_driver_status(self, driver_id: uuid.UUID, status: str) -> None:
        try:
            await self._redis.setex(
                self._status_key(driver_id),
                self._status_ttl,
                status,
            )
        except Exception as exc:
            logger.warning("Driver status cache set failed", error=str(exc))

    async def invalidate_pool(self, zone: str) -> None:
        try:
            await self._redis.delete(self._pool_key(zone))
        except Exception as exc:
            logger.warning("Driver pool cache invalidation failed", error=str(exc))
