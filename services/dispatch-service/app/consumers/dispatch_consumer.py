"""
services/dispatch-service/app/consumers/dispatch_consumer.py

Consumes:
  dispatch.requested → assign driver → publish driver.assigned
                     → simulate pickup → publish delivery.picked_up
                     → simulate delivery → publish delivery.completed
                                          or delivery.failed

This closes the final Saga arc:
  Order Service emits dispatch.requested (after order is READY_FOR_PICKUP)
  Dispatch Service assigns driver, emits driver.assigned
  Dispatch Service simulates progression, emits picked_up → completed/failed
  Order Service consumes each event and advances to DRIVER_ASSIGNED →
    OUT_FOR_DELIVERY → DELIVERED (or DELIVERY_FAILED)
"""

import asyncio
import random
import uuid

from app.cache.driver_cache import DriverCache
from app.core.config import get_settings
from app.services.dispatch_service import DispatchService, NoDriverAvailableError
from libs.common.db.session import get_session_factory
from libs.common.kafka.consumer import BaseKafkaConsumer
from libs.common.kafka.producer import KafkaProducer
from libs.common.logging import correlation_id_ctx, get_logger
from libs.common.schemas.base_event import BaseEvent
from libs.contracts.events.dispatch_events import (
    make_delivery_completed,
    make_delivery_failed,
    make_delivery_picked_up,
    make_driver_assigned,
)

logger = get_logger(__name__)

_processed_event_ids: set[str] = set()


class DispatchEventConsumer(BaseKafkaConsumer):

    def __init__(self, producer: KafkaProducer, redis_client, **kwargs) -> None:
        super().__init__(**kwargs)
        self._producer = producer
        self._redis = redis_client

    async def handle(self, event: BaseEvent) -> None:
        settings = get_settings()
        correlation_id_ctx.set(event.correlation_id)

        if event.event_type != "dispatch.requested":
            logger.warning("Unhandled event type", event_type=event.event_type)
            return

        payload = event.payload
        order_id = uuid.UUID(payload["order_id"])

        cache = DriverCache(
            redis_client=self._redis,
            status_ttl=settings.redis_driver_status_ttl,
            pool_ttl=settings.redis_driver_pool_ttl,
        )

        # ── Assign driver ─────────────────────────────────────────────────────
        try:
            async with get_session_factory()() as session:
                async with session.begin():
                    svc = DispatchService(session, cache)
                    assignment = await svc.assign_driver(
                        order_id=order_id,
                        source_event_id=event.event_id,
                    )
                    driver_name = assignment.driver.name if assignment.driver else "Driver"
                    driver_id = str(assignment.driver_id)
        except NoDriverAvailableError as exc:
            logger.error(
                "No driver available — sending delivery.failed",
                order_id=str(order_id),
                error=str(exc),
            )
            fail_event = make_delivery_failed(
                order_id=str(order_id),
                reason="No drivers available",
                causation_id=event.event_id,
            )
            await self._producer.publish(
                topic=settings.topic_delivery_failed,
                event=fail_event,
                key=str(order_id),
            )
            return

        # ── Publish driver.assigned ───────────────────────────────────────────
        assigned_event = make_driver_assigned(
            order_id=str(order_id),
            driver_id=driver_id,
            driver_name=driver_name,
            estimated_pickup_minutes=5,
            causation_id=event.event_id,
        )
        await self._producer.publish(
            topic=settings.topic_driver_assigned,
            event=assigned_event,
            key=str(order_id),
        )
        logger.info(
            "Published driver.assigned",
            order_id=str(order_id),
            driver_id=driver_id,
            driver_name=driver_name,
        )

        # ── Simulate delivery progression ─────────────────────────────────────
        asyncio.create_task(
            self._simulate_delivery(
                order_id=str(order_id),
                driver_id=driver_id,
                causation_event_id=assigned_event.event_id,
            )
        )

    async def _simulate_delivery(
        self,
        order_id: str,
        driver_id: str,
        causation_event_id: str,
    ) -> None:
        """
        Simulates pickup → delivery progression.
        In production this would be triggered by driver app GPS events.
        """
        settings = get_settings()
        order_uuid = uuid.UUID(order_id)

        # ── Simulate travel to restaurant ─────────────────────────────────────
        await asyncio.sleep(settings.simulated_pickup_delay)

        cache = DriverCache(self._redis)
        async with get_session_factory()() as session:
            async with session.begin():
                svc = DispatchService(session, cache)
                await svc.record_pickup(order_uuid)

        picked_up_event = make_delivery_picked_up(
            order_id=order_id,
            driver_id=driver_id,
            causation_id=causation_event_id,
        )
        await self._producer.publish(
            topic=settings.topic_delivery_picked_up,
            event=picked_up_event,
            key=order_id,
        )
        logger.info("Published delivery.picked_up", order_id=order_id)

        # ── Simulate travel to customer ───────────────────────────────────────
        await asyncio.sleep(settings.simulated_delivery_delay)

        # Probabilistic failure
        if random.random() < settings.simulated_delivery_failure_rate:
            async with get_session_factory()() as session:
                async with session.begin():
                    svc = DispatchService(session, cache)
                    await svc.record_failure(order_uuid, "Unable to complete delivery")

            fail_event = make_delivery_failed(
                order_id=order_id,
                driver_id=driver_id,
                reason="Unable to complete delivery",
                causation_id=picked_up_event.event_id,
            )
            await self._producer.publish(
                topic=settings.topic_delivery_failed,
                event=fail_event,
                key=order_id,
            )
            logger.warning("Published delivery.failed", order_id=order_id)
            return

        # ── Successful delivery ───────────────────────────────────────────────
        async with get_session_factory()() as session:
            async with session.begin():
                svc = DispatchService(session, cache)
                await svc.record_delivery(order_uuid)

        completed_event = make_delivery_completed(
            order_id=order_id,
            driver_id=driver_id,
            causation_id=picked_up_event.event_id,
        )
        await self._producer.publish(
            topic=settings.topic_delivery_completed,
            event=completed_event,
            key=order_id,
        )
        logger.info("Published delivery.completed", order_id=order_id)

    async def is_already_processed(self, event_id: str) -> bool:
        return event_id in _processed_event_ids

    async def mark_processed(self, event_id: str) -> None:
        _processed_event_ids.add(event_id)
