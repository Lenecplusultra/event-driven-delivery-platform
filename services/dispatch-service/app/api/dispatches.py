"""
services/dispatch-service/app/api/dispatches.py
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.cache.driver_cache import DriverCache
from app.core.config import get_settings
from app.core.dependencies import get_db, get_redis_client
from app.schemas.dispatch import DeliveryAssignmentResponse, DriverResponse
from app.services.dispatch_service import AssignmentNotFoundError, DispatchService
from libs.common.logging import get_logger

router = APIRouter(tags=["dispatch"])
logger = get_logger(__name__)


def _svc(db: AsyncSession = Depends(get_db)) -> DispatchService:
    settings = get_settings()
    cache = DriverCache(
        redis_client=get_redis_client(),
        status_ttl=settings.redis_driver_status_ttl,
        pool_ttl=settings.redis_driver_pool_ttl,
    )
    return DispatchService(db, cache)


@router.get("/assignments/order/{order_id}", response_model=DeliveryAssignmentResponse)
async def get_assignment(
    order_id: uuid.UUID,
    svc: DispatchService = Depends(_svc),
):
    try:
        return await svc.get_assignment(order_id)
    except AssignmentNotFoundError:
        raise HTTPException(status_code=404, detail=f"No assignment for order {order_id}")


@router.get("/drivers/available", response_model=list[DriverResponse])
async def list_available_drivers(
    zone: str = "default",
    db: AsyncSession = Depends(get_db),
):
    """List all currently available drivers. Useful for demos and debugging."""
    from app.repositories.dispatch_repository import DispatchRepository
    repo = DispatchRepository(db)
    return await repo.get_available_drivers(zone)
