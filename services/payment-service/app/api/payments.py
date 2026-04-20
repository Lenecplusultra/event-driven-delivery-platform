"""
services/payment-service/app/api/payments.py

HTTP routes for Payment Service.

Endpoints:
  GET  /payments/order/{order_id}        Get payment for an order
  POST /payments/order/{order_id}/refund Issue a refund (Saga compensating action)
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db
from app.schemas.payment import PaymentResponse, RefundRequest
from app.services.gateway_simulator import PaymentGatewaySimulator
from app.services.payment_service import (
    PaymentNotFoundError,
    PaymentService,
    RefundNotAllowedError,
)
from app.core.config import get_settings
from libs.common.logging import get_logger

router = APIRouter(prefix="/payments", tags=["payments"])
logger = get_logger(__name__)


def _service(db: AsyncSession = Depends(get_db)) -> PaymentService:
    settings = get_settings()
    gateway = PaymentGatewaySimulator(
        failure_rate=settings.simulated_failure_rate,
        processing_delay_seconds=settings.simulated_processing_delay,
        max_amount_cents=settings.max_transaction_amount_cents,
    )
    return PaymentService(db, gateway)


@router.get("/order/{order_id}", response_model=PaymentResponse)
async def get_payment_by_order(
    order_id: uuid.UUID,
    svc: PaymentService = Depends(_service),
):
    """Fetch the payment record for a given order ID."""
    try:
        return await svc.get_payment_by_order(order_id)
    except PaymentNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No payment found for order {order_id}",
        )


@router.post(
    "/order/{order_id}/refund",
    response_model=PaymentResponse,
    summary="Issue a refund",
)
async def refund_payment(
    order_id: uuid.UUID,
    body: RefundRequest,
    svc: PaymentService = Depends(_service),
):
    """
    Issue a full or partial refund for an authorized payment.
    This is the HTTP interface to the Saga compensating transaction.
    In production it would be triggered by an internal event, not a direct call.
    """
    try:
        return await svc.process_refund(order_id, body)
    except PaymentNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No payment found for order {order_id}",
        )
    except RefundNotAllowedError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        )
