"""
services/payment-service/app/consumers/payment_consumer.py

Kafka consumer for Payment Service.

Consumes:
  - payment.requested  →  authorize, publish payment.authorized or payment.failed

This closes the payment arc of the Saga:
  Order Service emits payment.requested
  Payment Service authorizes and emits payment.authorized or payment.failed
  Order Service consumes the result and advances state

DLQ routing:
  - Deserialization failure         → payment.requested.dlq immediately
  - Business logic exception        → retry up to MAX_RETRIES, then dlq
  - Gateway timeout (after retries) → dlq with failure_reason="gateway_timeout"

Idempotency is enforced at two levels:
  1. BaseKafkaConsumer.is_already_processed (event_id in memory)
  2. PaymentService.process_payment (event_id + idempotency_key in DB)

The second level is the durable one — survives service restarts.
"""

import uuid
from decimal import Decimal

from app.core.config import get_settings
from app.services.gateway_simulator import PaymentGatewaySimulator
from app.services.payment_service import PaymentService
from libs.common.db.session import get_session_factory
from libs.common.kafka.consumer import BaseKafkaConsumer
from libs.common.kafka.producer import KafkaProducer
from libs.common.logging import correlation_id_ctx, get_logger
from libs.common.schemas.base_event import BaseEvent
from libs.contracts.events.payment_events import make_payment_authorized, make_payment_failed

logger = get_logger(__name__)

# In-memory idempotency layer (fast path before DB check)
_processed_event_ids: set[str] = set()


class PaymentEventConsumer(BaseKafkaConsumer):
    """
    Consumes payment.requested events and emits authorization results.
    """

    def __init__(self, producer: KafkaProducer, **kwargs) -> None:
        super().__init__(**kwargs)
        self._producer = producer

    async def handle(self, event: BaseEvent) -> None:
        settings = get_settings()
        correlation_id_ctx.set(event.correlation_id)

        if event.event_type != "payment.requested":
            logger.warning("Unhandled event type", event_type=event.event_type)
            return

        payload = event.payload
        order_id = uuid.UUID(payload["order_id"])
        customer_id = uuid.UUID(payload["customer_id"])
        amount = Decimal(str(payload["amount"]))
        idempotency_key = payload["idempotency_key"]

        gateway = PaymentGatewaySimulator(
            failure_rate=settings.simulated_failure_rate,
            processing_delay_seconds=settings.simulated_processing_delay,
            max_amount_cents=settings.max_transaction_amount_cents,
        )

        async with get_session_factory()() as session:
            async with session.begin():
                svc = PaymentService(session, gateway)
                result = await svc.process_payment(
                    order_id=order_id,
                    customer_id=customer_id,
                    amount=amount,
                    idempotency_key=idempotency_key,
                    source_event_id=event.event_id,
                )

        # ── Publish result ────────────────────────────────────────────────────
        # If it already existed we still re-publish the outcome —
        # the Order Service consumer is idempotent and will ignore the duplicate.
        if result.authorized:
            out_event = make_payment_authorized(
                order_id=str(order_id),
                payment_id=str(result.payment.id),
                amount=amount,
                idempotency_key=idempotency_key,
                causation_id=event.event_id,
            )
            await self._producer.publish(
                topic=settings.topic_payment_authorized,
                event=out_event,
                key=str(order_id),
            )
            logger.info(
                "Published payment.authorized",
                order_id=str(order_id),
                payment_id=str(result.payment.id),
                correlation_id=event.correlation_id,
            )
        else:
            out_event = make_payment_failed(
                order_id=str(order_id),
                reason=result.failure_reason or "Unknown failure",
                idempotency_key=idempotency_key,
                payment_id=str(result.payment.id),
                causation_id=event.event_id,
            )
            await self._producer.publish(
                topic=settings.topic_payment_failed,
                event=out_event,
                key=str(order_id),
            )
            logger.warning(
                "Published payment.failed",
                order_id=str(order_id),
                reason=result.failure_reason,
                correlation_id=event.correlation_id,
            )

    # ── Idempotency ───────────────────────────────────────────────────────────

    async def is_already_processed(self, event_id: str) -> bool:
        return event_id in _processed_event_ids

    async def mark_processed(self, event_id: str) -> None:
        _processed_event_ids.add(event_id)
