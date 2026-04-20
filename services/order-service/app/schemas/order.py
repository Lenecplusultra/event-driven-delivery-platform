"""
services/order-service/app/schemas/order.py

Pydantic schemas for Order Service API request/response validation.
These are separate from ORM models — no SQLAlchemy types here.
"""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field, field_validator


# ── Request schemas ───────────────────────────────────────────────────────────


class DeliveryAddressIn(BaseModel):
    street: str = Field(..., min_length=1, max_length=255)
    city: str = Field(..., min_length=1, max_length=100)
    state: str = Field(..., min_length=2, max_length=2)
    zip_code: str = Field(..., pattern=r"^\d{5}(-\d{4})?$")
    country: str = Field(default="US", max_length=2)


class OrderItemIn(BaseModel):
    item_id: uuid.UUID
    name: str = Field(..., min_length=1, max_length=255)
    quantity: int = Field(..., ge=1, le=100)
    unit_price: Decimal = Field(..., gt=0, decimal_places=2)


class CreateOrderRequest(BaseModel):
    customer_id: uuid.UUID
    restaurant_id: uuid.UUID
    items: list[OrderItemIn] = Field(..., min_length=1)
    delivery_address: DeliveryAddressIn

    @field_validator("items")
    @classmethod
    def items_not_empty(cls, v: list) -> list:
        if not v:
            raise ValueError("Order must contain at least one item.")
        return v

    @property
    def total_amount(self) -> Decimal:
        return sum(item.unit_price * item.quantity for item in self.items)


# ── Response schemas ──────────────────────────────────────────────────────────


class OrderItemOut(BaseModel):
    id: uuid.UUID
    item_id: uuid.UUID
    name: str
    quantity: int
    unit_price: Decimal

    model_config = {"from_attributes": True}


class StatusHistoryEntry(BaseModel):
    id: uuid.UUID
    previous_status: str | None
    new_status: str
    triggered_by: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class OrderResponse(BaseModel):
    id: uuid.UUID
    customer_id: uuid.UUID
    restaurant_id: uuid.UUID
    status: str
    total_amount: Decimal
    delivery_address: dict[str, Any]
    items: list[OrderItemOut]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class OrderDetailResponse(OrderResponse):
    """Includes full status history. Used by GET /orders/{id}/history."""
    status_history: list[StatusHistoryEntry]

    model_config = {"from_attributes": True}
