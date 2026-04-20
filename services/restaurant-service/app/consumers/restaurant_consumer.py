"""
services/restaurant-service/app/consumers/restaurant_consumer.py

Kafka consumer for Restaurant Service.

Consumes:
  - order.created  →  validate items, decide confirm/reject, publish result

This is the event that closes the first arc of the Saga:
  Order Service emits order.created
  Restaurant Service validates and emits restaurant.order_confirmed or rejected
  Order Service consumes the response and advances state

Flow for each order.created event:
  1. Extract order_id, restaurant_id, item_ids from payload
  2. Idempotency check (source_event_id against order_confirmations table)
  3. Check restaurant is OPEN
  4. Bulk-check item availability (Redis cache → DB fallback)
  5. Record confirmation decision in DB
  6. Publish restaurant.order_confirmed or restaurant.order_rejected
  7. If confirmed and auto_confirm_orders: simulate prep progression
"""

import asyncio
import uuid

from app.cache.menu_cache import MenuCache
from app.core.config import get_settings
from app.models.restaurant import OrderConfirmationDecision
from app.services.restaurant_service import RestaurantService
from libs.common.db.session import get_session_factory
from libs.common.kafka.consumer import BaseKafkaConsumer
from libs.common.kafka.producer import KafkaProducer
from libs.common.logging import correlation_id_ctx, get_logger
from libs.common.schemas.base_event import BaseEvent
from libs.contracts.events.restaurant_events import (
    make_order_confirmed,
    make_order_preparing,
    make_order_ready_for_pickup,
    make_order_rejected,
)

logger = get_logger(__name__)

# ── In-memory idempotency store ───────────────────────────────────────────────
# Phase 1: simple set. Phase 2: replace with Redis SETNX with TTL.
_processed_event_ids: set[str] = set()


class RestaurantEventConsumer(BaseKafkaConsumer):
    """
    Consumes order.created events and emits confirmation or rejection.
    """

    def __init__(
        self,
        producer: KafkaProducer,
        redis_client,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._producer = producer
        self._redis = redis_client

    async def handle(self, event: BaseEvent) -> None:
        settings = get_settings()
        correlation_id_ctx.set(event.correlation_id)

        if event.event_type != "order.created":
            logger.warning("Unhandled event type", event_type=event.event_type)
            return

        payload = event.payload
        order_id = uuid.UUID(payload["order_id"])
        restaurant_id = uuid.UUID(payload["restaurant_id"])
        item_ids = [uuid.UUID(item["item_id"]) for item in payload.get("items", [])]

        cache = MenuCache(
            redis_client=self._redis,
            menu_ttl=settings.redis_menu_ttl,
            item_ttl=settings.redis_item_avail_ttl,
        )

        async with get_session_factory()() as session:
            async with session.begin():
                service = RestaurantService(session, cache)
                confirmation = await service.confirm_order(
                    order_id=order_id,
                    restaurant_id=restaurant_id,
                    item_ids=item_ids,
                    source_event_id=event.event_id,
                )

        # ── Publish confirmation/rejection ────────────────────────────────────
        if confirmation.decision == OrderConfirmationDecision.CONFIRMED.value:
            confirm_event = make_order_confirmed(
                order_id=str(order_id),
                restaurant_id=str(restaurant_id),
                causation_id=event.event_id,
            )
            await self._producer.publish(
                topic=settings.topic_order_confirmed,
                event=confirm_event,
                key=str(order_id),
            )
            logger.info(
                "Published restaurant.order_confirmed",
                order_id=str(order_id),
                correlation_id=event.correlation_id,
            )

            # ── Simulate kitchen prep progression (local dev) ─────────────────
            if settings.auto_confirm_orders:
                asyncio.create_task(
                    self._simulate_preparation(
                        order_id=str(order_id),
                        restaurant_id=str(restaurant_id),
                        causation_event_id=confirm_event.event_id,
                        delay=settings.auto_confirm_delay_seconds,
                    )
                )

        else:
            reject_event = make_order_rejected(
                order_id=str(order_id),
                restaurant_id=str(restaurant_id),
                reason=confirmation.rejection_reason or "Order rejected",
                causation_id=event.event_id,
            )
            await self._producer.publish(
                topic=settings.topic_order_rejected,
                event=reject_event,
                key=str(order_id),
            )
            logger.info(
                "Published restaurant.order_rejected",
                order_id=str(order_id),
                reason=confirmation.rejection_reason,
            )

    async def _simulate_preparation(
        self,
        order_id: str,
        restaurant_id: str,
        causation_event_id: str,
        delay: float = 2.0,
    ) -> None:
        """
        Simulates the kitchen accepting and preparing the order.
        After payment is authorized, emits order.preparing → order.ready_for_pickup.

        NOTE: In production, these events would be triggered by a real kitchen
        display system or restaurant operator action. Here we simulate them
        automatically so the full Saga can run end-to-end locally without
        a human operator.
        """
        settings = get_settings()

        # Wait for payment to be processed (in a real system, we'd listen for
        # payment.authorized first — this is a simplification for local dev)
        await asyncio.sleep(delay * 4)

        preparing_event = make_order_preparing(
            order_id=order_id,
            restaurant_id=restaurant_id,
            estimated_ready_minutes=10,
            causation_id=causation_event_id,
        )
        await self._producer.publish(
            topic=settings.topic_order_preparing,
            event=preparing_event,
            key=order_id,
        )
        logger.info("Simulated order.preparing", order_id=order_id)

        # Simulate 10 seconds of prep time
        await asyncio.sleep(delay * 10)

        ready_event = make_order_ready_for_pickup(
            order_id=order_id,
            restaurant_id=restaurant_id,
            causation_id=preparing_event.event_id,
        )
        await self._producer.publish(
            topic=settings.topic_order_ready,
            event=ready_event,
            key=order_id,
        )
        logger.info("Simulated order.ready_for_pickup", order_id=order_id)

    # ── Idempotency ───────────────────────────────────────────────────────────

    async def is_already_processed(self, event_id: str) -> bool:
        return event_id in _processed_event_ids

    async def mark_processed(self, event_id: str) -> None:
        _processed_event_ids.add(event_id)
