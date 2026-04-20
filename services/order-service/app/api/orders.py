"""
services/order-service/app/api/orders.py

HTTP route handlers for Order Service.

Endpoints:
  POST /orders                      Create a new order
  GET  /orders/{order_id}           Fetch order with items
  GET  /orders/{order_id}/history   Fetch full status transition history

Idempotency-Key header is required on POST. If a request arrives with a
key that already exists, we return the existing order with HTTP 200
instead of creating a duplicate.
"""

import uuid

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db
from app.schemas.order import CreateOrderRequest, OrderDetailResponse, OrderResponse
from app.services.order_service import (
    DuplicateOrderError,
    InvalidStateTransitionError,
    OrderNotFoundError,
    OrderService,
)
from libs.common.logging import correlation_id_ctx, get_logger

router = APIRouter(prefix="/orders", tags=["orders"])
logger = get_logger(__name__)


def _get_order_service(db: AsyncSession = Depends(get_db)) -> OrderService:
    return OrderService(db)


@router.post(
    "",
    response_model=OrderResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new order",
    responses={
        200: {"description": "Order already exists for this idempotency key (returned unchanged)"},
        201: {"description": "Order created"},
        422: {"description": "Validation error"},
    },
)
async def create_order(
    request: Request,
    body: CreateOrderRequest,
    idempotency_key: str = Header(
        ...,
        alias="Idempotency-Key",
        description="Client-generated UUID. Repeated requests with the same key return the existing order.",
    ),
    service: OrderService = Depends(_get_order_service),
):
    """
    Create a new order.

    The `Idempotency-Key` header (UUID) is required.
    If an order with this key already exists, the existing order is returned
    with HTTP 200 — no duplicate is created.
    """
    # ── Inject correlation_id into log context for this request ───────────────
    # Will be overwritten by the real order_id once we know it
    correlation_id_ctx.set(idempotency_key)

    try:
        order = await service.create_order(body, idempotency_key)
        correlation_id_ctx.set(str(order.id))
        logger.info(
            "Order created via API",
            order_id=str(order.id),
            customer_id=str(order.customer_id),
        )
        return order

    except DuplicateOrderError as exc:
        # Idempotent replay — return existing order with 200
        logger.info(
            "Idempotent replay: returning existing order",
            order_id=str(exc.existing_order.id),
            idempotency_key=idempotency_key,
        )
        from fastapi.responses import JSONResponse
        from app.schemas.order import OrderResponse as Schema
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content=Schema.model_validate(exc.existing_order).model_dump(mode="json"),
        )


@router.get(
    "/{order_id}",
    response_model=OrderResponse,
    summary="Get order by ID",
)
async def get_order(
    order_id: uuid.UUID,
    service: OrderService = Depends(_get_order_service),
):
    correlation_id_ctx.set(str(order_id))
    try:
        return await service.get_order(order_id)
    except OrderNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Order {order_id} not found",
        )


@router.get(
    "/{order_id}/history",
    response_model=OrderDetailResponse,
    summary="Get full order status history",
)
async def get_order_history(
    order_id: uuid.UUID,
    service: OrderService = Depends(_get_order_service),
):
    correlation_id_ctx.set(str(order_id))
    try:
        order = await service.get_order(order_id)
        return order
    except OrderNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Order {order_id} not found",
        )
