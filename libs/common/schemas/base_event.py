"""
libs/common/schemas/base_event.py

The canonical event envelope every service uses when publishing to Kafka.

Every event MUST include these fields. The `payload` field carries
event-specific data defined in libs/contracts/events/*.py.

Never publish raw dicts to Kafka — always serialize a BaseEvent subclass.
"""

import uuid
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field


def _utc_now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _new_uuid() -> str:
    return str(uuid.uuid4())


class BaseEvent(BaseModel):
    """
    Shared envelope for all domain events.

    Producers fill in all fields before publishing.
    Consumers must validate incoming messages against this schema.
    """

    event_id: str = Field(default_factory=_new_uuid)
    event_type: str                         # e.g. "order.created"
    schema_version: int = 1
    occurred_at: datetime = Field(default_factory=_utc_now)
    correlation_id: str                     # = order_id for order-centric events
    causation_id: str | None = None         # event_id of the event that triggered this one
    aggregate_type: str                     # e.g. "Order"
    aggregate_id: str                       # e.g. order UUID
    producer: str                           # e.g. "order-service"
    payload: dict[str, Any] = Field(default_factory=dict)

    class Config:
        json_encoders = {datetime: lambda v: v.isoformat()}
