"""
services/restaurant-service/app/api/restaurants.py

HTTP routes for Restaurant Service.

Endpoints:
  POST /restaurants                           Create restaurant + optional menu
  GET  /restaurants/{id}                      Get restaurant with full menu
  GET  /restaurants/{id}/menu                 Get menu (Redis cache first)
  PATCH /restaurants/{id}/status              Open or close restaurant
  PATCH /restaurants/{id}/items/{item_id}     Toggle item availability
  POST /restaurants/{id}/availability-check   Bulk item availability check
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.cache.menu_cache import MenuCache
from app.core.config import get_settings
from app.core.dependencies import get_cache, get_db
from app.schemas.restaurant import (
    ItemAvailabilityRequest,
    ItemAvailabilityResponse,
    MenuItemUpdate,
    RestaurantCreate,
    RestaurantDetailResponse,
    RestaurantResponse,
    RestaurantUpdate,
)
from app.services.restaurant_service import RestaurantNotFoundError, RestaurantService
from libs.common.logging import get_logger

router = APIRouter(prefix="/restaurants", tags=["restaurants"])
logger = get_logger(__name__)


def _service(
    db: AsyncSession = Depends(get_db),
    cache: MenuCache = Depends(get_cache),
) -> RestaurantService:
    return RestaurantService(db, cache)


@router.post("", response_model=RestaurantResponse, status_code=status.HTTP_201_CREATED)
async def create_restaurant(
    body: RestaurantCreate,
    svc: RestaurantService = Depends(_service),
):
    r = await svc.create_restaurant(body)
    return r


@router.get("/{restaurant_id}", response_model=RestaurantDetailResponse)
async def get_restaurant(
    restaurant_id: uuid.UUID,
    svc: RestaurantService = Depends(_service),
):
    try:
        return await svc.get_restaurant(restaurant_id)
    except RestaurantNotFoundError:
        raise HTTPException(status_code=404, detail=f"Restaurant {restaurant_id} not found")


@router.get("/{restaurant_id}/menu")
async def get_menu(
    restaurant_id: uuid.UUID,
    svc: RestaurantService = Depends(_service),
):
    """Returns menu from Redis cache. Populates cache on miss."""
    try:
        return await svc.get_menu_cached(restaurant_id)
    except RestaurantNotFoundError:
        raise HTTPException(status_code=404, detail=f"Restaurant {restaurant_id} not found")


@router.patch("/{restaurant_id}/open", response_model=RestaurantResponse)
async def open_restaurant(
    restaurant_id: uuid.UUID,
    svc: RestaurantService = Depends(_service),
):
    try:
        return await svc.set_open(restaurant_id)
    except RestaurantNotFoundError:
        raise HTTPException(status_code=404, detail=f"Restaurant {restaurant_id} not found")


@router.patch("/{restaurant_id}/close", response_model=RestaurantResponse)
async def close_restaurant(
    restaurant_id: uuid.UUID,
    svc: RestaurantService = Depends(_service),
):
    try:
        return await svc.set_closed(restaurant_id)
    except RestaurantNotFoundError:
        raise HTTPException(status_code=404, detail=f"Restaurant {restaurant_id} not found")


@router.patch(
    "/{restaurant_id}/items/{item_id}/availability",
    status_code=status.HTTP_200_OK,
)
async def update_item_availability(
    restaurant_id: uuid.UUID,
    item_id: uuid.UUID,
    body: MenuItemUpdate,
    svc: RestaurantService = Depends(_service),
):
    """Toggle a menu item's availability. Invalidates Redis cache."""
    if body.is_available is None:
        raise HTTPException(status_code=422, detail="is_available field required")
    item = await svc.update_item_availability(item_id, body.is_available)
    return {"item_id": str(item.id), "is_available": item.is_available}


@router.post("/{restaurant_id}/availability-check", response_model=ItemAvailabilityResponse)
async def check_availability(
    restaurant_id: uuid.UUID,
    body: ItemAvailabilityRequest,
    svc: RestaurantService = Depends(_service),
):
    """Bulk availability check for a list of item IDs. Cache-first."""
    availability = await svc.check_items_available(restaurant_id, body.item_ids)
    return ItemAvailabilityResponse(
        restaurant_id=restaurant_id,
        items=availability,
    )
