"""
services/restaurant-service/app/cache/menu_cache.py

Redis caching layer for restaurant menus and item availability.

Cache design (from SPEC.md §10):
  Key                          TTL     Purpose
  menu:{restaurant_id}         5 min   Full restaurant + menu JSON
  item:avail:{item_id}         2 min   Single item availability boolean

Write-through invalidation:
  - On any restaurant/menu update → delete menu:{restaurant_id}
  - On item availability update   → delete item:avail:{item_id}

This keeps the cache simple and always-consistent:
miss → read from DB → repopulate cache → return.
"""

import json
import uuid
from typing import Any

import redis.asyncio as aioredis

from libs.common.logging import get_logger

logger = get_logger(__name__)


class MenuCache:
    def __init__(self, redis_client: aioredis.Redis, menu_ttl: int, item_ttl: int) -> None:
        self._redis = redis_client
        self._menu_ttl = menu_ttl
        self._item_ttl = item_ttl

    # ── Full menu cache ───────────────────────────────────────────────────────

    def _menu_key(self, restaurant_id: uuid.UUID | str) -> str:
        return f"menu:{restaurant_id}"

    async def get_menu(self, restaurant_id: uuid.UUID) -> dict[str, Any] | None:
        try:
            raw = await self._redis.get(self._menu_key(restaurant_id))
            if raw:
                logger.debug("Menu cache hit", restaurant_id=str(restaurant_id))
                return json.loads(raw)
            logger.debug("Menu cache miss", restaurant_id=str(restaurant_id))
            return None
        except Exception as exc:
            # Cache failures must never break the request path
            logger.warning("Menu cache get failed", error=str(exc))
            return None

    async def set_menu(self, restaurant_id: uuid.UUID, data: dict[str, Any]) -> None:
        try:
            await self._redis.setex(
                self._menu_key(restaurant_id),
                self._menu_ttl,
                json.dumps(data, default=str),
            )
            logger.debug(
                "Menu cached",
                restaurant_id=str(restaurant_id),
                ttl=self._menu_ttl,
            )
        except Exception as exc:
            logger.warning("Menu cache set failed", error=str(exc))

    async def invalidate_menu(self, restaurant_id: uuid.UUID) -> None:
        try:
            await self._redis.delete(self._menu_key(restaurant_id))
            logger.info("Menu cache invalidated", restaurant_id=str(restaurant_id))
        except Exception as exc:
            logger.warning("Menu cache invalidation failed", error=str(exc))

    # ── Item availability cache ───────────────────────────────────────────────

    def _item_key(self, item_id: uuid.UUID | str) -> str:
        return f"item:avail:{item_id}"

    async def get_item_availability(self, item_id: uuid.UUID) -> bool | None:
        try:
            raw = await self._redis.get(self._item_key(item_id))
            if raw is not None:
                return raw == b"1"
            return None
        except Exception as exc:
            logger.warning("Item availability cache get failed", error=str(exc))
            return None

    async def set_item_availability(self, item_id: uuid.UUID, is_available: bool) -> None:
        try:
            await self._redis.setex(
                self._item_key(item_id),
                self._item_ttl,
                "1" if is_available else "0",
            )
        except Exception as exc:
            logger.warning("Item availability cache set failed", error=str(exc))

    async def invalidate_item(self, item_id: uuid.UUID) -> None:
        try:
            await self._redis.delete(self._item_key(item_id))
        except Exception as exc:
            logger.warning("Item availability cache invalidation failed", error=str(exc))

    async def get_items_availability_bulk(
        self, item_ids: list[uuid.UUID]
    ) -> dict[str, bool | None]:
        """
        Fetch availability for multiple items in one pipeline round-trip.
        Returns dict of {item_id_str: bool | None} where None = cache miss.
        """
        result: dict[str, bool | None] = {}
        if not item_ids:
            return result

        try:
            pipe = self._redis.pipeline()
            for item_id in item_ids:
                pipe.get(self._item_key(item_id))
            values = await pipe.execute()

            for item_id, raw in zip(item_ids, values):
                if raw is not None:
                    result[str(item_id)] = raw == b"1"
                else:
                    result[str(item_id)] = None
        except Exception as exc:
            logger.warning("Bulk item availability cache failed", error=str(exc))
            for item_id in item_ids:
                result[str(item_id)] = None

        return result
