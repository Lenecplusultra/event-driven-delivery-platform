"""
libs/contracts/events/dispatch_events.py

Typed event contracts for Dispatch Service domain events.
"""

from pydantic import BaseModel
from libs.common.schemas.base_event import BaseEvent


class DriverAssignedPayload(BaseModel):
    order_id: str
    driver_id: str
    driver_name: str
    estimated_pickup_minutes: int


class DeliveryPickedUpPayload(BaseModel):
    order_id: str
    driver_id: str


class DeliveryCompletedPayload(BaseModel):
    order_id: str
    driver_id: str


class DeliveryFailedPayload(BaseModel):
    order_id: str
    driver_id: str | None
    reason: str


def make_driver_assigned(
    order_id: str,
    driver_id: str,
    driver_name: str,
    estimated_pickup_minutes: int = 5,
    causation_id: str | None = None,
) -> BaseEvent:
    return BaseEvent(
        event_type="driver.assigned",
        correlation_id=order_id,
        causation_id=causation_id,
        aggregate_type="Delivery",
        aggregate_id=order_id,
        producer="dispatch-service",
        payload=DriverAssignedPayload(
            order_id=order_id,
            driver_id=driver_id,
            driver_name=driver_name,
            estimated_pickup_minutes=estimated_pickup_minutes,
        ).model_dump(),
    )


def make_delivery_picked_up(
    order_id: str,
    driver_id: str,
    causation_id: str | None = None,
) -> BaseEvent:
    return BaseEvent(
        event_type="delivery.picked_up",
        correlation_id=order_id,
        causation_id=causation_id,
        aggregate_type="Delivery",
        aggregate_id=order_id,
        producer="dispatch-service",
        payload=DeliveryPickedUpPayload(order_id=order_id, driver_id=driver_id).model_dump(),
    )


def make_delivery_completed(
    order_id: str,
    driver_id: str,
    causation_id: str | None = None,
) -> BaseEvent:
    return BaseEvent(
        event_type="delivery.completed",
        correlation_id=order_id,
        causation_id=causation_id,
        aggregate_type="Delivery",
        aggregate_id=order_id,
        producer="dispatch-service",
        payload=DeliveryCompletedPayload(order_id=order_id, driver_id=driver_id).model_dump(),
    )


def make_delivery_failed(
    order_id: str,
    reason: str,
    driver_id: str | None = None,
    causation_id: str | None = None,
) -> BaseEvent:
    return BaseEvent(
        event_type="delivery.failed",
        correlation_id=order_id,
        causation_id=causation_id,
        aggregate_type="Delivery",
        aggregate_id=order_id,
        producer="dispatch-service",
        payload=DeliveryFailedPayload(
            order_id=order_id, driver_id=driver_id, reason=reason
        ).model_dump(),
    )
