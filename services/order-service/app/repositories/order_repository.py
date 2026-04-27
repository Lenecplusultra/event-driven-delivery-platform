"""
services/order-service/app/repositories/order_repository.py

Data access layer for Order Service.

All DB writes that also need a Kafka event use the outbox pattern:
  1. Write the order state change
  2. Write an outbox record
  3. Both in a single transaction — if the transaction fails, neither persists

Never call the Kafka producer directly from a repository.
The outbox relay handles publication.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.order import Order, OrderItem, OrderStatusHistory, Outbox
from libs.common.logging import get_logger
from libs.common.schemas.base_event import BaseEvent

logger = get_logger(__name__)


class OrderRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ── Reads ─────────────────────────────────────────────────────────────────

    async def get_by_id(self, order_id: uuid.UUID) -> Order | None:
        result = await self._session.execute(
            select(Order)
            .options(selectinload(Order.items))
            .where(Order.id == order_id)
        )
        return result.scalar_one_or_none()

    async def get_by_idempotency_key(self, key: str) -> Order | None:
        result = await self._session.execute(
            select(Order)
            .options(selectinload(Order.items))
            .where(Order.idempotency_key == key)
        )
        return result.scalar_one_or_none()

    async def get_order_history(self, order_id: uuid.UUID) -> list[OrderStatusHistory]:
        result = await self._session.execute(
            select(OrderStatusHistory)
            .where(OrderStatusHistory.order_id == order_id)
            .order_by(OrderStatusHistory.created_at)
        )
        return list(result.scalars().all())

    # ── Writes ────────────────────────────────────────────────────────────────

    async def create(
        self,
        order: Order,
        items: list[OrderItem],
        outbox_event: BaseEvent,
        topic: str,
    ) -> Order:
        """
        Persist a new order, its items, the initial status history entry,
        and the order.created outbox record — all in one transaction.
        """
        self._session.add(order)
        for item in items:
            self._session.add(item)

        history = OrderStatusHistory(
            order_id=order.id,
            previous_status=None,
            new_status=order.status,
            triggered_by="POST /orders",
        )
        self._session.add(history)

        outbox = Outbox(
            event_type=outbox_event.event_type,
            topic=topic,
            payload=outbox_event.model_dump(mode="json"),
            partition_key=str(order.id),
        )
        self._session.add(outbox)

        await self._session.flush()
        await self._session.refresh(order, attribute_names=["items"])

        logger.info(
            "Order persisted with outbox record",
            order_id=str(order.id),
            event_type=outbox_event.event_type,
        )
        return order

    async def transition_status(
        self,
        order_id: uuid.UUID,
        new_status: str,
        triggered_by: str,
        event_id: uuid.UUID | None = None,
        outbox_event: BaseEvent | None = None,
        topic: str | None = None,
    ) -> Order:
        """
        Apply a state transition and optionally write an outbox record.
        Both writes are atomic in the caller's transaction.
        """
        order = await self.get_by_id(order_id)
        if order is None:
            raise ValueError(f"Order {order_id} not found")

        previous_status = order.status
        order.status = new_status
        order.updated_at = datetime.now(tz=timezone.utc)

        history = OrderStatusHistory(
            order_id=order.id,
            previous_status=previous_status,
            new_status=new_status,
            triggered_by=triggered_by,
            event_id=event_id,
        )
        self._session.add(history)

        if outbox_event and topic:
            outbox = Outbox(
                event_type=outbox_event.event_type,
                topic=topic,
                payload=outbox_event.model_dump(mode="json"),
                partition_key=str(order_id),
            )
            self._session.add(outbox)

        await self._session.flush()
        logger.info(
            "Order status transitioned",
            order_id=str(order_id),
            previous_status=previous_status,
            new_status=new_status,
            triggered_by=triggered_by,
        )
        return order

    async def get_unpublished_outbox(self, limit: int = 100) -> list[Outbox]:
        """Fetch unpublished outbox records for the relay process."""
        result = await self._session.execute(
            select(Outbox)
            .where(Outbox.published == False)  # noqa: E712
            .order_by(Outbox.created_at)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def mark_outbox_published(self, outbox_id: uuid.UUID) -> None:
        await self._session.execute(
            update(Outbox)
            .where(Outbox.id == outbox_id)
            .values(published=True, published_at=datetime.now(tz=timezone.utc))
        )
