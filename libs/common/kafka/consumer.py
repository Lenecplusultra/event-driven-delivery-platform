"""
libs/common/kafka/consumer.py

Async Kafka consumer base class used by all services.

Features:
  - Idempotency check before processing (delegates to subclass)
  - Correlation ID injection into context vars for log correlation
  - OpenTelemetry span wrapping every message handler
  - Automatic DLQ forwarding after max retry exhaustion
  - Structured logging of every consumed message

Usage:
    class OrderEventConsumer(BaseKafkaConsumer):
        async def handle(self, event: BaseEvent) -> None:
            if event.event_type == "restaurant.order_confirmed":
                await self.order_service.confirm(event)

    consumer = OrderEventConsumer(
        topics=["restaurant.order_confirmed", "payment.authorized"],
        group_id="order-service-group",
        bootstrap_servers="localhost:9092",
        dlq_producer=producer,
    )
    await consumer.start()
"""

import json
from abc import ABC, abstractmethod

from aiokafka import AIOKafkaConsumer, ConsumerRecord
from opentelemetry import trace

from libs.common.logging import correlation_id_ctx, causation_id_ctx, get_logger
from libs.common.schemas.base_event import BaseEvent

logger = get_logger(__name__)

MAX_RETRIES = 3


class BaseKafkaConsumer(ABC):
    def __init__(
        self,
        topics: list[str],
        group_id: str,
        bootstrap_servers: str,
        dlq_producer=None,          # KafkaProducer instance, optional
    ) -> None:
        self._topics = topics
        self._group_id = group_id
        self._bootstrap_servers = bootstrap_servers
        self._dlq_producer = dlq_producer
        self._consumer: AIOKafkaConsumer | None = None
        self._running = False

    async def start(self) -> None:
        self._consumer = AIOKafkaConsumer(
            *self._topics,
            bootstrap_servers=self._bootstrap_servers,
            group_id=self._group_id,
            value_deserializer=lambda v: json.loads(v.decode("utf-8")),
            auto_offset_reset="earliest",
            enable_auto_commit=False,       # manual commit after successful processing
        )
        await self._consumer.start()
        self._running = True
        logger.info(
            "Kafka consumer started",
            topics=self._topics,
            group_id=self._group_id,
        )
        await self._consume_loop()

    async def stop(self) -> None:
        self._running = False
        if self._consumer:
            await self._consumer.stop()
            logger.info("Kafka consumer stopped")

    async def _consume_loop(self) -> None:
        async for record in self._consumer:
            await self._process_record(record)

    async def _process_record(self, record: ConsumerRecord) -> None:
        raw = record.value
        tracer = trace.get_tracer(__name__)

        try:
            event = BaseEvent.model_validate(raw)
        except Exception as exc:
            logger.error(
                "Failed to deserialize event — sending to DLQ",
                error=str(exc),
                raw=str(raw)[:500],
            )
            await self._send_to_dlq(record.topic, raw, "deserialization_failure")
            await self._consumer.commit()
            return

        # ── Inject correlation IDs into context vars ──────────────────
        correlation_id_ctx.set(event.correlation_id)
        if event.causation_id:
            causation_id_ctx.set(event.causation_id)

        with tracer.start_as_current_span(f"kafka.consume.{event.event_type}") as span:
            span.set_attribute("messaging.system", "kafka")
            span.set_attribute("messaging.source", record.topic)
            span.set_attribute("messaging.operation", "receive")
            span.set_attribute("correlation_id", event.correlation_id)
            span.set_attribute("event.type", event.event_type)
            span.set_attribute("event.id", event.event_id)

            # ── Idempotency check ─────────────────────────────────────
            if await self.is_already_processed(event.event_id):
                logger.info(
                    "Duplicate event ignored",
                    event_id=event.event_id,
                    event_type=event.event_type,
                    correlation_id=event.correlation_id,
                )
                await self._consumer.commit()
                return

            # ── Process with retry ────────────────────────────────────
            last_error: Exception | None = None
            for attempt in range(1, MAX_RETRIES + 1):
                try:
                    await self.handle(event)
                    await self.mark_processed(event.event_id)
                    await self._consumer.commit()
                    logger.info(
                        "Event processed",
                        event_type=event.event_type,
                        event_id=event.event_id,
                        correlation_id=event.correlation_id,
                    )
                    return
                except Exception as exc:
                    last_error = exc
                    logger.warning(
                        "Event processing failed",
                        attempt=attempt,
                        max_retries=MAX_RETRIES,
                        event_type=event.event_type,
                        error=str(exc),
                    )

            # ── All retries exhausted → DLQ ───────────────────────────
            span.record_exception(last_error)
            logger.error(
                "Event sent to DLQ after max retries",
                event_type=event.event_type,
                event_id=event.event_id,
                error=str(last_error),
            )
            await self._send_to_dlq(
                record.topic,
                raw,
                failure_reason=str(last_error),
            )
            await self._consumer.commit()

    async def _send_to_dlq(
        self, source_topic: str, payload: dict, failure_reason: str
    ) -> None:
        if not self._dlq_producer:
            return
        dlq_topic = f"{source_topic}.dlq"
        dlq_payload = {**payload, "failure_reason": failure_reason, "source_topic": source_topic}
        await self._dlq_producer.publish_raw(dlq_topic, dlq_payload)

    # ── Abstract methods — implemented by each service's consumer ─────

    @abstractmethod
    async def handle(self, event: BaseEvent) -> None:
        """Process a validated, non-duplicate event."""
        ...

    async def is_already_processed(self, event_id: str) -> bool:
        """
        Return True if this event_id was already successfully processed.
        Override in each service to check against local idempotency store.
        Default: always False (no deduplication — override this!).
        """
        return False

    async def mark_processed(self, event_id: str) -> None:
        """
        Mark an event_id as successfully processed.
        Override in each service to persist to local idempotency store.
        """
        pass
