"""
services/dispatch-service/app/schemas/dispatch.py
"""

import uuid
from datetime import datetime
from pydantic import BaseModel, Field


class DriverResponse(BaseModel):
    id: uuid.UUID
    name: str
    zone: str
    status: str
    model_config = {"from_attributes": True}


class DeliveryAssignmentResponse(BaseModel):
    id: uuid.UUID
    order_id: uuid.UUID
    driver_id: uuid.UUID
    status: str
    failure_reason: str | None
    assigned_at: datetime
    picked_up_at: datetime | None
    delivered_at: datetime | None
    model_config = {"from_attributes": True}
