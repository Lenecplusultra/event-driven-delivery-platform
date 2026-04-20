"""
libs/contracts/events/order_events.py

Typed event contracts for Order Service domain events.

These are the "public API" of the Order Service.
Every service that consumes order events imports these classes.
"""

from decimal import Decimal
from typing import Any

from pydantic import BaseModel

from libs.common.schemas.base_event import BaseEvent

# ── Payload models ────────────────────────────────────────────────────────────


class OrderItemPayload(BaseModel):
    item_id: str
    name: str
    quantity: int
    unit_price: Decimal


class DeliveryAddressPayload(BaseModel):
    street: str
    city: str
    state: str
    zip_code: str
    country: str = "US"


class OrderCreatedPayload(BaseModel):
    order_id: str
    customer_id: str
    restaurant_id: str
    items: list[OrderItemPayload]
    total_amount: Decimal
    delivery_address: DeliveryAddressPayload
    idempotency_key: str


class OrderStatusUpdatedPayload(BaseModel):
    order_id: str
    previous_status: str
    new_status: str
    triggered_by: str           # event_type or actor name


class PaymentRequestedPayload(BaseModel):
    order_id: str
    customer_id: str
    amount: Decimal
    idempotency_key: str        # payment-specific idempotency key


class DispatchRequestedPayload(BaseModel):
    order_id: str
    restaurant_id: str
    delivery_address: DeliveryAddressPayload


# ── Event factories ───────────────────────────────────────────────────────────


def make_order_created(
    order_id: str,
    customer_id: str,
    restaurant_id: str,
    items: list[dict[str, Any]],
    total_amount: Decimal,
    delivery_address: dict[str, Any],
    idempotency_key: str,
    causation_id: str | None = None,
) -> BaseEvent:
    return BaseEvent(
        event_type="order.created",
        correlation_id=order_id,
        causation_id=causation_id,
        aggregate_type="Order",
        aggregate_id=order_id,
        producer="order-service",
        payload=OrderCreatedPayload(
            order_id=order_id,
            customer_id=customer_id,
            restaurant_id=restaurant_id,
            items=[OrderItemPayload(**i) for i in items],
            total_amount=total_amount,
            delivery_address=DeliveryAddressPayload(**delivery_address),
            idempotency_key=idempotency_key,
        ).model_dump(mode="json"),
    )


def make_payment_requested(
    order_id: str,
    customer_id: str,
    amount: Decimal,
    idempotency_key: str,
    causation_id: str | None = None,
) -> BaseEvent:
    return BaseEvent(
        event_type="payment.requested",
        correlation_id=order_id,
        causation_id=causation_id,
        aggregate_type="Order",
        aggregate_id=order_id,
        producer="order-service",
        payload=PaymentRequestedPayload(
            order_id=order_id,
            customer_id=customer_id,
            amount=amount,
            idempotency_key=idempotency_key,
        ).model_dump(mode="json"),
    )


def make_dispatch_requested(
    order_id: str,
    restaurant_id: str,
    delivery_address: dict[str, Any],
    causation_id: str | None = None,
) -> BaseEvent:
    return BaseEvent(
        event_type="dispatch.requested",
        correlation_id=order_id,
        causation_id=causation_id,
        aggregate_type="Order",
        aggregate_id=order_id,
        producer="order-service",
        payload=DispatchRequestedPayload(
            order_id=order_id,
            restaurant_id=restaurant_id,
            delivery_address=DeliveryAddressPayload(**delivery_address),
        ).model_dump(mode="json"),
    )
