"""
services/restaurant-service/app/services/restaurant_service.py

Business logic layer for Restaurant Service.

Responsibilities:
  - Restaurant and menu CRUD
  - Item availability validation for incoming orders
  - Order confirm/reject decisions with idempotency
  - Cache population and invalidation via MenuCache
"""

import asyncio
import uuid
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.cache.menu_cache import MenuCache
from app.models.restaurant import (
    Menu,
    MenuItem,
    OrderConfirmation,
    OrderConfirmationDecision,
    Restaurant,
    RestaurantStatus,
)
from app.repositories.restaurant_repository import RestaurantRepository
from app.schemas.restaurant import RestaurantCreate
from libs.common.logging import get_logger

logger = get_logger(__name__)


class RestaurantNotFoundError(Exception):
    pass


class ItemNotAvailableError(Exception):
    def __init__(self, item_id: str, reason: str = "") -> None:
        self.item_id = item_id
        super().__init__(f"Item {item_id} not available: {reason}")


class RestaurantService:
    def __init__(self, session: AsyncSession, cache: MenuCache) -> None:
        self._repo = RestaurantRepository(session)
        self._cache = cache

    # ── Restaurant CRUD ───────────────────────────────────────────────────────

    async def create_restaurant(self, data: RestaurantCreate) -> Restaurant:
        restaurant = Restaurant(
            name=data.name,
            description=data.description,
            address=data.address,
            phone=data.phone,
            status=RestaurantStatus.CLOSED.value,
        )

        if data.menu:
            menu = Menu(name=data.menu.name, is_active=True)
            menu.items = [
                MenuItem(
                    name=item.name,
                    description=item.description,
                    price=float(item.price),
                    is_available=item.is_available,
                    stock_count=item.stock_count,
                )
                for item in data.menu.items
            ]
            restaurant.menus = [menu]

        created = await self._repo.create_restaurant(restaurant)
        logger.info("Restaurant created", restaurant_id=str(created.id), name=created.name)
        return created

    async def get_restaurant(self, restaurant_id: uuid.UUID) -> Restaurant:
        r = await self._repo.get_by_id(restaurant_id)
        if r is None:
            raise RestaurantNotFoundError(f"Restaurant {restaurant_id} not found")
        return r

    async def set_open(self, restaurant_id: uuid.UUID) -> Restaurant:
        r = await self._repo.update_status(restaurant_id, RestaurantStatus.OPEN.value)
        if r is None:
            raise RestaurantNotFoundError(f"Restaurant {restaurant_id} not found")
        await self._cache.invalidate_menu(restaurant_id)
        return r

    async def set_closed(self, restaurant_id: uuid.UUID) -> Restaurant:
        r = await self._repo.update_status(restaurant_id, RestaurantStatus.CLOSED.value)
        if r is None:
            raise RestaurantNotFoundError(f"Restaurant {restaurant_id} not found")
        await self._cache.invalidate_menu(restaurant_id)
        return r

    # ── Menu cache ────────────────────────────────────────────────────────────

    async def get_menu_cached(self, restaurant_id: uuid.UUID) -> dict:
        """
        Return the restaurant menu from Redis cache.
        On cache miss: fetch from DB, populate cache, return.
        """
        cached = await self._cache.get_menu(restaurant_id)
        if cached is not None:
            return cached

        restaurant = await self.get_restaurant(restaurant_id)
        serialized = _serialize_restaurant(restaurant)
        await self._cache.set_menu(restaurant_id, serialized)
        return serialized

    # ── Item availability ─────────────────────────────────────────────────────

    async def check_items_available(
        self, restaurant_id: uuid.UUID, item_ids: list[uuid.UUID]
    ) -> dict[str, bool]:
        """
        Check availability for a list of item IDs.

        Strategy:
          1. Bulk-fetch from Redis cache
          2. For any cache miss, fetch from DB
          3. Populate cache for each miss
          4. Return full availability map
        """
        cache_results = await self._cache.get_items_availability_bulk(item_ids)

        # Collect IDs that were not in cache
        miss_ids = [
            item_id for item_id in item_ids
            if cache_results.get(str(item_id)) is None
        ]

        if miss_ids:
            db_items = await self._repo.get_items_by_ids(miss_ids)
            for item in db_items:
                cache_results[str(item.id)] = item.is_available
                await self._cache.set_item_availability(item.id, item.is_available)

        return {k: v for k, v in cache_results.items() if v is not None}

    async def update_item_availability(
        self, item_id: uuid.UUID, is_available: bool
    ) -> MenuItem:
        item = await self._repo.update_item_availability(item_id, is_available)
        if item is None:
            raise ValueError(f"Item {item_id} not found")
        # Invalidate item cache + parent menu cache
        await self._cache.invalidate_item(item_id)
        db_item = await self._repo.get_item(item_id)
        if db_item:
            # Also invalidate the restaurant menu cache (contains this item)
            menu = db_item.menu
            if menu:
                await self._cache.invalidate_menu(menu.restaurant_id)
        return item

    # ── Order confirm / reject ────────────────────────────────────────────────

    async def confirm_order(
        self,
        order_id: uuid.UUID,
        restaurant_id: uuid.UUID,
        item_ids: list[uuid.UUID],
        source_event_id: str,
    ) -> OrderConfirmation:
        """
        Validate item availability and record a CONFIRMED decision.
        Idempotent — if a confirmation already exists for this event, return it.
        """
        # ── Idempotency check ─────────────────────────────────────────────────
        if await self._repo.confirmation_exists_for_event(source_event_id):
            existing = await self._repo.get_confirmation(order_id)
            logger.info(
                "Duplicate order.created event — returning existing confirmation",
                order_id=str(order_id),
                source_event_id=source_event_id,
            )
            return existing

        # ── Validate restaurant is open ───────────────────────────────────────
        restaurant = await self._repo.get_by_id(restaurant_id)
        if restaurant is None or restaurant.status != RestaurantStatus.OPEN.value:
            return await self._record_rejection(
                order_id=order_id,
                restaurant_id=restaurant_id,
                source_event_id=source_event_id,
                reason="Restaurant is not open",
            )

        # ── Validate all items are available ──────────────────────────────────
        availability = await self.check_items_available(restaurant_id, item_ids)
        unavailable = [str(iid) for iid in item_ids if not availability.get(str(iid), False)]

        if unavailable:
            return await self._record_rejection(
                order_id=order_id,
                restaurant_id=restaurant_id,
                source_event_id=source_event_id,
                reason=f"Items unavailable: {', '.join(unavailable)}",
            )

        confirmation = OrderConfirmation(
            order_id=order_id,
            restaurant_id=restaurant_id,
            decision=OrderConfirmationDecision.CONFIRMED.value,
            source_event_id=source_event_id,
        )
        saved = await self._repo.save_confirmation(confirmation)
        logger.info(
            "Order confirmed",
            order_id=str(order_id),
            restaurant_id=str(restaurant_id),
        )
        return saved

    async def _record_rejection(
        self,
        order_id: uuid.UUID,
        restaurant_id: uuid.UUID,
        source_event_id: str,
        reason: str,
    ) -> OrderConfirmation:
        confirmation = OrderConfirmation(
            order_id=order_id,
            restaurant_id=restaurant_id,
            decision=OrderConfirmationDecision.REJECTED.value,
            rejection_reason=reason,
            source_event_id=source_event_id,
        )
        saved = await self._repo.save_confirmation(confirmation)
        logger.warning(
            "Order rejected",
            order_id=str(order_id),
            restaurant_id=str(restaurant_id),
            reason=reason,
        )
        return saved


# ── Serialization helper ──────────────────────────────────────────────────────

def _serialize_restaurant(restaurant: Restaurant) -> dict:
    """Serialize a Restaurant ORM object to a plain dict for caching."""
    return {
        "id": str(restaurant.id),
        "name": restaurant.name,
        "status": restaurant.status,
        "menus": [
            {
                "id": str(menu.id),
                "name": menu.name,
                "items": [
                    {
                        "id": str(item.id),
                        "name": item.name,
                        "price": str(item.price),
                        "is_available": item.is_available,
                    }
                    for item in menu.items
                ],
            }
            for menu in restaurant.menus
            if menu.is_active
        ],
    }
