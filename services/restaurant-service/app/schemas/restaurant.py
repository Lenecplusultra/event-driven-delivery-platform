"""
services/restaurant-service/app/schemas/restaurant.py

Pydantic request/response schemas for Restaurant Service API.
"""

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field


# ── Menu Item ─────────────────────────────────────────────────────────────────

class MenuItemCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    price: Decimal = Field(..., gt=0, decimal_places=2)
    is_available: bool = True
    stock_count: int | None = Field(None, ge=0)


class MenuItemUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = None
    price: Decimal | None = Field(None, gt=0, decimal_places=2)
    is_available: bool | None = None
    stock_count: int | None = Field(None, ge=0)


class MenuItemResponse(BaseModel):
    id: uuid.UUID
    menu_id: uuid.UUID
    name: str
    description: str | None
    price: Decimal
    is_available: bool
    stock_count: int | None

    model_config = {"from_attributes": True}


# ── Menu ──────────────────────────────────────────────────────────────────────

class MenuCreate(BaseModel):
    name: str = Field(default="Main Menu", max_length=255)
    items: list[MenuItemCreate] = Field(default_factory=list)


class MenuResponse(BaseModel):
    id: uuid.UUID
    restaurant_id: uuid.UUID
    name: str
    is_active: bool
    items: list[MenuItemResponse]

    model_config = {"from_attributes": True}


# ── Restaurant ────────────────────────────────────────────────────────────────

class RestaurantCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    address: str = Field(..., min_length=1, max_length=500)
    phone: str | None = None
    menu: MenuCreate | None = None


class RestaurantUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = None
    address: str | None = Field(None, min_length=1, max_length=500)
    phone: str | None = None
    status: str | None = None


class RestaurantResponse(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    status: str
    address: str
    phone: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class RestaurantDetailResponse(RestaurantResponse):
    """Includes full menu. Used for cache population."""
    menus: list[MenuResponse]

    model_config = {"from_attributes": True}


# ── Availability check (used by order validation) ─────────────────────────────

class ItemAvailabilityRequest(BaseModel):
    item_ids: list[uuid.UUID]


class ItemAvailabilityResponse(BaseModel):
    restaurant_id: uuid.UUID
    items: dict[str, bool]     # item_id (str) → is_available
