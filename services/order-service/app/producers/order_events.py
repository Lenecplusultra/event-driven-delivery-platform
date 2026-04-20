"""
services/order-service/app/producers/order_events.py

Outbox relay for Order Service.

The relay runs as a background task alongside the FastAPI app.
It polls the outbox table for unpublished records and publishes them
to Kafka, then marks them as published.

This is the implementation of the Outbox Pattern:
  - Order state changes + outbox writes are atomic (same DB transaction)
  - Kafka publish is a separate, retryable step
  - If Kafka is down, events queue in the DB and are published when it recovers
  - No event is ever lost because the DB commit happened first

The relay uses a simple polling loop for Phase 1.
In production, this could be replaced by Debezium CDC (Change Data Capture).
"""

import asyncio

from app.repositories.order_repository import OrderRepository
from libs.common.db.session import get_session_factory
from libs.common.kafka.producer import KafkaProducer
from libs.common.logging import get_logger
from libs.common.schemas.base_event import BaseEvent

logger = get_logger(__name__)

POLL_INTERVAL_SECONDS = 1.0
BATCH_SIZE = 100


class OutboxRelay:
    """
    Polls the outbox table and publishes unpublished events to Kafka.
    Runs as an asyncio background task started in main.py lifespan.
    """

    def __init__(self, producer: KafkaProducer) -> None:
        self._producer = producer
        self._running = False

    async def start(self) -> None:
        self._running = True
        logger.info("Outbox relay started")
        while self._running:
            try:
                await self._relay_batch()
            except Exception as exc:
                logger.error("Outbox relay error", error=str(exc))
            await asyncio.sleep(POLL_INTERVAL_SECONDS)

    async def stop(self) -> None:
        self._running = False
        logger.info("Outbox relay stopped")

    async def _relay_batch(self) -> None:
        factory = get_session_factory()
        async with factory() as session:
            async with session.begin():
                repo = OrderRepository(session)
                records = await repo.get_unpublished_outbox(limit=BATCH_SIZE)

                if not records:
                    return

                for record in records:
                    try:
                        event = BaseEvent.model_validate(record.payload)
                        await self._producer.publish(
                            topic=record.topic,
                            event=event,
                            key=record.partition_key,
                        )
                        await repo.mark_outbox_published(record.id)
                        logger.info(
                            "Outbox record published",
                            outbox_id=str(record.id),
                            topic=record.topic,
                            event_type=record.event_type,
                        )
                    except Exception as exc:
                        # Log but continue — don't fail the whole batch for one record.
                        # The record stays unpublished and will be retried on next poll.
                        logger.error(
                            "Failed to publish outbox record",
                            outbox_id=str(record.id),
                            event_type=record.event_type,
                            error=str(exc),
                        )
