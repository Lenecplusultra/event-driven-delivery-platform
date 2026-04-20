"""
services/payment-service/app/schemas/payment.py

Pydantic schemas for Payment Service.
"""

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field


class PaymentAttemptResponse(BaseModel):
    id: uuid.UUID
    result: str
    failure_reason: str | None
    gateway_reference: str | None
    processing_duration_ms: int | None
    attempted_at: datetime

    model_config = {"from_attributes": True}


class PaymentResponse(BaseModel):
    id: uuid.UUID
    order_id: uuid.UUID
    customer_id: uuid.UUID
    idempotency_key: str
    amount_cents: int
    currency: str
    status: str
    failure_reason: str | None
    refunded_amount_cents: int
    created_at: datetime
    updated_at: datetime
    attempts: list[PaymentAttemptResponse] = []

    model_config = {"from_attributes": True}


class RefundRequest(BaseModel):
    reason: str = Field(..., min_length=1, max_length=255)
    amount_cents: int | None = Field(
        None, gt=0, description="Partial refund amount. Omit for full refund."
    )
