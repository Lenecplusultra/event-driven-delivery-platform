"""
libs/contracts/events/restaurant_events.py

Typed event contracts for Restaurant Service domain events.
"""

from pydantic import BaseModel

from libs.common.schemas.base_event import BaseEvent


class RestaurantOrderConfirmedPayload(BaseModel):
    order_id: str
    restaurant_id: str


class RestaurantOrderRejectedPayload(BaseModel):
    order_id: str
    restaurant_id: str
    reason: str


class OrderPreparingPayload(BaseModel):
    order_id: str
    restaurant_id: str
    estimated_ready_minutes: int


class OrderReadyForPickupPayload(BaseModel):
    order_id: str
    restaurant_id: str


def make_order_confirmed(
    order_id: str,
    restaurant_id: str,
    causation_id: str | None = None,
) -> BaseEvent:
    return BaseEvent(
        event_type="restaurant.order_confirmed",
        correlation_id=order_id,
        causation_id=causation_id,
        aggregate_type="Order",
        aggregate_id=order_id,
        producer="restaurant-service",
        payload=RestaurantOrderConfirmedPayload(
            order_id=order_id,
            restaurant_id=restaurant_id,
        ).model_dump(),
    )


def make_order_rejected(
    order_id: str,
    restaurant_id: str,
    reason: str,
    causation_id: str | None = None,
) -> BaseEvent:
    return BaseEvent(
        event_type="restaurant.order_rejected",
        correlation_id=order_id,
        causation_id=causation_id,
        aggregate_type="Order",
        aggregate_id=order_id,
        producer="restaurant-service",
        payload=RestaurantOrderRejectedPayload(
            order_id=order_id,
            restaurant_id=restaurant_id,
            reason=reason,
        ).model_dump(),
    )


def make_order_preparing(
    order_id: str,
    restaurant_id: str,
    estimated_ready_minutes: int = 15,
    causation_id: str | None = None,
) -> BaseEvent:
    return BaseEvent(
        event_type="order.preparing",
        correlation_id=order_id,
        causation_id=causation_id,
        aggregate_type="Order",
        aggregate_id=order_id,
        producer="restaurant-service",
        payload=OrderPreparingPayload(
            order_id=order_id,
            restaurant_id=restaurant_id,
            estimated_ready_minutes=estimated_ready_minutes,
        ).model_dump(),
    )


def make_order_ready_for_pickup(
    order_id: str,
    restaurant_id: str,
    causation_id: str | None = None,
) -> BaseEvent:
    return BaseEvent(
        event_type="order.ready_for_pickup",
        correlation_id=order_id,
        causation_id=causation_id,
        aggregate_type="Order",
        aggregate_id=order_id,
        producer="restaurant-service",
        payload=OrderReadyForPickupPayload(
            order_id=order_id,
            restaurant_id=restaurant_id,
        ).model_dump(),
    )
