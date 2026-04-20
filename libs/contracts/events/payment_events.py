"""
libs/contracts/events/payment_events.py

Typed event contracts for Payment Service domain events.
"""

from decimal import Decimal

from pydantic import BaseModel

from libs.common.schemas.base_event import BaseEvent


class PaymentAuthorizedPayload(BaseModel):
    order_id: str
    payment_id: str
    amount: Decimal
    idempotency_key: str


class PaymentFailedPayload(BaseModel):
    order_id: str
    payment_id: str | None
    reason: str
    idempotency_key: str


class PaymentRefundedPayload(BaseModel):
    order_id: str
    payment_id: str
    amount: Decimal
    reason: str


def make_payment_authorized(
    order_id: str,
    payment_id: str,
    amount: Decimal,
    idempotency_key: str,
    causation_id: str | None = None,
) -> BaseEvent:
    return BaseEvent(
        event_type="payment.authorized",
        correlation_id=order_id,
        causation_id=causation_id,
        aggregate_type="Payment",
        aggregate_id=payment_id,
        producer="payment-service",
        payload=PaymentAuthorizedPayload(
            order_id=order_id,
            payment_id=payment_id,
            amount=amount,
            idempotency_key=idempotency_key,
        ).model_dump(mode="json"),
    )


def make_payment_failed(
    order_id: str,
    reason: str,
    idempotency_key: str,
    payment_id: str | None = None,
    causation_id: str | None = None,
) -> BaseEvent:
    return BaseEvent(
        event_type="payment.failed",
        correlation_id=order_id,
        causation_id=causation_id,
        aggregate_type="Payment",
        aggregate_id=payment_id or order_id,
        producer="payment-service",
        payload=PaymentFailedPayload(
            order_id=order_id,
            payment_id=payment_id,
            reason=reason,
            idempotency_key=idempotency_key,
        ).model_dump(mode="json"),
    )
