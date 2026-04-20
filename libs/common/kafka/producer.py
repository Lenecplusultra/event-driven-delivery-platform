"""
libs/common/kafka/producer.py

Async Kafka producer wrapper used by all services.

Features:
  - Singleton producer per service process
  - JSON serialization of BaseEvent envelopes
  - Partition by key (order_id) for per-order ordering
  - OpenTelemetry span on every publish
  - Structured logging of publish success/failure

Usage:
    from libs.common.kafka.producer import KafkaProducer

    producer = KafkaProducer(bootstrap_servers="localhost:9092")
    await producer.start()

    await producer.publish(
        topic="order.created",
        event=order_created_event,
        key=order_id,          # ensures same partition for same order
    )

    await producer.stop()
"""

import json
from typing import Any

from aiokafka import AIOKafkaProducer
from opentelemetry import trace

from libs.common.logging import get_logger
from libs.common.schemas.base_event import BaseEvent

logger = get_logger(__name__)


class KafkaProducer:
    def __init__(self, bootstrap_servers: str) -> None:
        self._bootstrap_servers = bootstrap_servers
        self._producer: AIOKafkaProducer | None = None

    async def start(self) -> None:
        self._producer = AIOKafkaProducer(
            bootstrap_servers=self._bootstrap_servers,
            value_serializer=lambda v: json.dumps(v).encode("utf-8"),
            key_serializer=lambda k: k.encode("utf-8") if k else None,
            enable_idempotence=True,        # producer-side idempotency
            acks="all",                     # wait for all in-sync replicas
            compression_type="lz4",
        )
        await self._producer.start()
        logger.info("Kafka producer started", bootstrap_servers=self._bootstrap_servers)

    async def stop(self) -> None:
        if self._producer:
            await self._producer.stop()
            logger.info("Kafka producer stopped")

    async def publish(
        self,
        topic: str,
        event: BaseEvent,
        key: str | None = None,
    ) -> None:
        """
        Serialize and publish a domain event.

        Args:
            topic:  Kafka topic name (e.g. "order.created")
            event:  BaseEvent subclass instance
            key:    Partition key — use order_id for order-centric events
        """
        if not self._producer:
            raise RuntimeError("KafkaProducer not started. Call start() first.")

        tracer = trace.get_tracer(__name__)
        with tracer.start_as_current_span(f"kafka.publish.{event.event_type}") as span:
            span.set_attribute("messaging.system", "kafka")
            span.set_attribute("messaging.destination", topic)
            span.set_attribute("messaging.operation", "publish")
            span.set_attribute("correlation_id", event.correlation_id)
            span.set_attribute("event.type", event.event_type)
            span.set_attribute("event.id", event.event_id)

            payload = event.model_dump(mode="json")

            try:
                await self._producer.send_and_wait(topic, value=payload, key=key)
                logger.info(
                    "Event published",
                    topic=topic,
                    event_type=event.event_type,
                    event_id=event.event_id,
                    correlation_id=event.correlation_id,
                )
            except Exception as exc:
                span.record_exception(exc)
                logger.error(
                    "Failed to publish event",
                    topic=topic,
                    event_type=event.event_type,
                    event_id=event.event_id,
                    error=str(exc),
                )
                raise

    async def publish_raw(self, topic: str, payload: dict[str, Any], key: str | None = None) -> None:
        """Publish a raw dict — use only for DLQ forwarding."""
        if not self._producer:
            raise RuntimeError("KafkaProducer not started. Call start() first.")
        await self._producer.send_and_wait(topic, value=payload, key=key)
