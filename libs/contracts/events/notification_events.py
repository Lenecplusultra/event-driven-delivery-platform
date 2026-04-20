"""
libs/contracts/events/notification_events.py

Typed event contracts for Notification Service domain events.
"""

from typing import Literal

from pydantic import BaseModel

from libs.common.schemas.base_event import BaseEvent

NotificationChannel = Literal["email", "sms", "in_app"]


class NotificationRequestedPayload(BaseModel):
    recipient_id: str
    recipient_type: Literal["customer", "driver", "restaurant"]
    channels: list[NotificationChannel]
    template_id: str
    template_vars: dict


def make_notification_requested(
    correlation_id: str,
    recipient_id: str,
    recipient_type: str,
    channels: list[str],
    template_id: str,
    template_vars: dict,
    causation_id: str | None = None,
) -> BaseEvent:
    return BaseEvent(
        event_type="notification.requested",
        correlation_id=correlation_id,
        causation_id=causation_id,
        aggregate_type="Notification",
        aggregate_id=correlation_id,
        producer="order-service",
        payload=NotificationRequestedPayload(
            recipient_id=recipient_id,
            recipient_type=recipient_type,
            channels=channels,
            template_id=template_id,
            template_vars=template_vars,
        ).model_dump(mode="json"),
    )
