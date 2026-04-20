"""
services/order-service/app/consumers/order_consumer.py

Kafka consumer for Order Service.

Consumes events from Restaurant, Payment, and Dispatch Services
and drives order state machine transitions via OrderService.

Each handler:
  1. Validates the event is for a known order
  2. Calls OrderService.transition() with the event_type
  3. transition() validates the state machine and writes the new state + outbox
  4. Session is committed by the base consumer after handle() returns

Idempotency is enforced by BaseKafkaConsumer — duplicate event_ids are
dropped before handle() is ever called.
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.order_service import (
    InvalidStateTransitionError,
    OrderNotFoundError,
    OrderService,
)
from libs.common.db.session import get_session_factory
from libs.common.kafka.consumer import BaseKafkaConsumer
from libs.common.logging import correlation_id_ctx, get_logger
from libs.common.schemas.base_event import BaseEvent

logger = get_logger(__name__)

# ── In-memory idempotency store (replace with Redis or DB in production) ──────
# For Phase 1 local dev, a set is fine. For production, use a DB table or Redis
# with a TTL long enough to cover any possible replay window (e.g. 48 hours).
_processed_event_ids: set[str] = set()


class OrderEventConsumer(BaseKafkaConsumer):
    """
    Consumes lifecycle events from Restaurant, Payment, and Dispatch Services
    and drives Order state machine transitions.
    """

    HANDLED_EVENTS = {
        "restaurant.order_confirmed",
        "restaurant.order_rejected",
        "payment.authorized",
        "payment.failed",
        "order.preparing",
        "order.ready_for_pickup",
        "driver.assigned",
        "delivery.picked_up",
        "delivery.completed",
        "delivery.failed",
    }

    async def handle(self, event: BaseEvent) -> None:
        """
        Route the event to the correct handler method.
        All handlers share the same pattern: validate → transition → done.
        """
        # Set correlation_id in log context
        correlation_id_ctx.set(event.correlation_id)

        if event.event_type not in self.HANDLED_EVENTS:
            logger.warning(
                "Received unhandled event type — skipping",
                event_type=event.event_type,
                event_id=event.event_id,
            )
            return

        order_id = uuid.UUID(event.aggregate_id)

        async with get_session_factory()() as session:
            async with session.begin():
                service = OrderService(session)
                try:
                    await service.transition(
                        order_id=order_id,
                        event_type=event.event_type,
                        triggered_by=event.event_type,
                        causation_event_id=event.event_id,
                        extra_payload=event.payload,
                    )
                    logger.info(
                        "State transition applied",
                        event_type=event.event_type,
                        order_id=str(order_id),
                        correlation_id=event.correlation_id,
                    )
                except OrderNotFoundError:
                    logger.error(
                        "Order not found for event",
                        event_type=event.event_type,
                        order_id=str(order_id),
                    )
                    raise
                except InvalidStateTransitionError as exc:
                    # Log and swallow — this event arrived out of order or is stale.
                    # Do not route to DLQ; the order is in a valid final state.
                    logger.warning(
                        "Invalid state transition — event dropped",
                        event_type=event.event_type,
                        order_id=str(order_id),
                        reason=str(exc),
                    )

    # ── Idempotency ───────────────────────────────────────────────────────────

    async def is_already_processed(self, event_id: str) -> bool:
        return event_id in _processed_event_ids

    async def mark_processed(self, event_id: str) -> None:
        _processed_event_ids.add(event_id)
