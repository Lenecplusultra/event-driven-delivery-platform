"""
services/restaurant-service/app/repositories/restaurant_repository.py

Data access layer for Restaurant Service.
All queries return ORM objects. The service layer handles business logic.
"""

import uuid

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.restaurant import Menu, MenuItem, OrderConfirmation, Restaurant
from libs.common.logging import get_logger

logger = get_logger(__name__)


class RestaurantRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ── Restaurant ────────────────────────────────────────────────────────────

    async def create_restaurant(self, restaurant: Restaurant) -> Restaurant:
        self._session.add(restaurant)
        await self._session.flush()
        return restaurant

    async def get_by_id(self, restaurant_id: uuid.UUID) -> Restaurant | None:
        result = await self._session.execute(
            select(Restaurant)
            .options(selectinload(Restaurant.menus).selectinload(Menu.items))
            .where(Restaurant.id == restaurant_id)
        )
        return result.scalar_one_or_none()

    async def list_open(self) -> list[Restaurant]:
        result = await self._session.execute(
            select(Restaurant)
            .options(selectinload(Restaurant.menus).selectinload(Menu.items))
            .where(Restaurant.status == "OPEN")
            .order_by(Restaurant.name)
        )
        return list(result.scalars().all())

    async def update_status(self, restaurant_id: uuid.UUID, status: str) -> Restaurant | None:
        await self._session.execute(
            update(Restaurant)
            .where(Restaurant.id == restaurant_id)
            .values(status=status)
        )
        await self._session.flush()
        return await self.get_by_id(restaurant_id)

    # ── Menu items ────────────────────────────────────────────────────────────

    async def get_item(self, item_id: uuid.UUID) -> MenuItem | None:
        result = await self._session.execute(
            select(MenuItem).where(MenuItem.id == item_id)
        )
        return result.scalar_one_or_none()

    async def get_items_by_ids(self, item_ids: list[uuid.UUID]) -> list[MenuItem]:
        result = await self._session.execute(
            select(MenuItem).where(MenuItem.id.in_(item_ids))
        )
        return list(result.scalars().all())

    async def update_item_availability(
        self, item_id: uuid.UUID, is_available: bool
    ) -> MenuItem | None:
        await self._session.execute(
            update(MenuItem)
            .where(MenuItem.id == item_id)
            .values(is_available=is_available)
        )
        await self._session.flush()
        return await self.get_item(item_id)

    # ── Order confirmations ───────────────────────────────────────────────────

    async def get_confirmation(self, order_id: uuid.UUID) -> OrderConfirmation | None:
        result = await self._session.execute(
            select(OrderConfirmation).where(OrderConfirmation.order_id == order_id)
        )
        return result.scalar_one_or_none()

    async def save_confirmation(self, confirmation: OrderConfirmation) -> OrderConfirmation:
        self._session.add(confirmation)
        await self._session.flush()
        return confirmation

    async def confirmation_exists_for_event(self, source_event_id: str) -> bool:
        result = await self._session.execute(
            select(OrderConfirmation).where(
                OrderConfirmation.source_event_id == source_event_id
            )
        )
        return result.scalar_one_or_none() is not None
