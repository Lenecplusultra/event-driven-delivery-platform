"""
services/payment-service/app/services/payment_service.py

Business logic layer for Payment Service.

Responsibilities:
  - Process payment.requested events with strict idempotency
  - Call the gateway simulator for authorization
  - Persist payment + attempt records
  - Return result (AUTHORIZED or FAILED) for the consumer to publish
  - Handle refund requests triggered by Saga compensating transactions

Idempotency contract:
  1. Check processed_events table by event_id FIRST (before any DB write)
  2. Check payments table by idempotency_key SECOND (prevents duplicate payments)
  3. If either exists → return existing outcome, publish no new event, done

This two-layer check means:
  - Same event_id consumed twice → caught by layer 1
  - Different event_id but same idempotency_key (legitimate client retry) →
    caught by layer 2 → return existing payment result
"""

import time
import uuid
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.payment import Payment, PaymentAttempt, PaymentAttemptResult, PaymentStatus
from app.repositories.payment_repository import PaymentRepository
from app.schemas.payment import RefundRequest
from app.services.gateway_simulator import GatewayResult, PaymentGatewaySimulator
from libs.common.logging import get_logger

logger = get_logger(__name__)


class PaymentAlreadyProcessedError(Exception):
    """Raised when the idempotency check finds an existing payment."""
    def __init__(self, payment: Payment) -> None:
        self.payment = payment
        super().__init__(f"Payment already processed for order {payment.order_id}")


class PaymentNotFoundError(Exception):
    pass


class RefundNotAllowedError(Exception):
    pass


class ProcessPaymentResult:
    """Value object returned by process_payment()."""
    def __init__(
        self,
        payment: Payment,
        authorized: bool,
        failure_reason: str | None = None,
        already_existed: bool = False,
    ) -> None:
        self.payment = payment
        self.authorized = authorized
        self.failure_reason = failure_reason
        self.already_existed = already_existed


class PaymentService:
    def __init__(self, session: AsyncSession, gateway: PaymentGatewaySimulator) -> None:
        self._repo = PaymentRepository(session)
        self._gateway = gateway

    # ── Process payment.requested ─────────────────────────────────────────────

    async def process_payment(
        self,
        order_id: uuid.UUID,
        customer_id: uuid.UUID,
        amount: Decimal,
        idempotency_key: str,
        source_event_id: str,
    ) -> ProcessPaymentResult:
        """
        Authorize a payment for an order.

        Idempotency guarantees:
          - If source_event_id was already processed → return existing result
          - If idempotency_key already has a payment → return existing payment
          - Otherwise → call gateway, persist, return new result

        Amount is stored as integer cents to avoid floating-point precision issues.
        """
        amount_cents = _to_cents(amount)

        # ── Layer 1: event-level idempotency ──────────────────────────────────
        if await self._repo.is_event_processed(source_event_id):
            existing = await self._repo.get_by_order_id(order_id)
            if existing:
                logger.info(
                    "Duplicate event — returning existing payment",
                    event_id=source_event_id,
                    payment_id=str(existing.id),
                    order_id=str(order_id),
                )
                return ProcessPaymentResult(
                    payment=existing,
                    authorized=(existing.status == PaymentStatus.AUTHORIZED.value),
                    failure_reason=existing.failure_reason,
                    already_existed=True,
                )

        # ── Layer 2: payment-level idempotency ────────────────────────────────
        existing = await self._repo.get_by_idempotency_key(idempotency_key)
        if existing:
            logger.info(
                "Idempotency key already used — returning existing payment",
                idempotency_key=idempotency_key,
                payment_id=str(existing.id),
                order_id=str(order_id),
            )
            return ProcessPaymentResult(
                payment=existing,
                authorized=(existing.status == PaymentStatus.AUTHORIZED.value),
                failure_reason=existing.failure_reason,
                already_existed=True,
            )

        # ── Create pending payment record ─────────────────────────────────────
        payment = Payment(
            order_id=order_id,
            customer_id=customer_id,
            idempotency_key=idempotency_key,
            amount_cents=amount_cents,
            status=PaymentStatus.PENDING.value,
        )
        payment = await self._repo.create_payment(payment)

        # ── Call gateway ──────────────────────────────────────────────────────
        logger.info(
            "Calling payment gateway",
            payment_id=str(payment.id),
            order_id=str(order_id),
            amount_cents=amount_cents,
        )
        try:
            gateway_response = await self._gateway.authorize(
                amount_cents=amount_cents,
                idempotency_key=idempotency_key,
            )
        except Exception as exc:
            # Gateway timeout or unexpected error → treat as failure
            gateway_response = None
            failure_reason = f"Gateway error: {exc}"
            logger.error(
                "Gateway call failed",
                payment_id=str(payment.id),
                error=str(exc),
            )
            await self._repo.record_attempt(
                PaymentAttempt(
                    payment_id=payment.id,
                    result=PaymentAttemptResult.TIMEOUT.value,
                    failure_reason=failure_reason,
                )
            )
            await self._repo.update_status(
                payment.id, PaymentStatus.FAILED.value, failure_reason
            )
            await self._repo.mark_event_processed(source_event_id, "FAILED")
            payment = await self._repo.get_by_id(payment.id)
            return ProcessPaymentResult(
                payment=payment,
                authorized=False,
                failure_reason=failure_reason,
            )

        # ── Record attempt ────────────────────────────────────────────────────
        attempt_result = (
            PaymentAttemptResult.SUCCESS.value
            if gateway_response.result == GatewayResult.AUTHORIZED
            else PaymentAttemptResult.FAILURE.value
        )
        await self._repo.record_attempt(
            PaymentAttempt(
                payment_id=payment.id,
                result=attempt_result,
                failure_reason=gateway_response.failure_reason,
                gateway_reference=gateway_response.gateway_reference,
                processing_duration_ms=gateway_response.processing_duration_ms,
            )
        )

        # ── Update payment status ─────────────────────────────────────────────
        if gateway_response.result == GatewayResult.AUTHORIZED:
            new_status = PaymentStatus.AUTHORIZED.value
            failure_reason = None
        else:
            new_status = PaymentStatus.FAILED.value
            failure_reason = gateway_response.failure_reason

        await self._repo.update_status(payment.id, new_status, failure_reason)
        await self._repo.mark_event_processed(
            source_event_id,
            "AUTHORIZED" if gateway_response.result == GatewayResult.AUTHORIZED else "FAILED",
        )

        payment = await self._repo.get_by_id(payment.id)

        logger.info(
            "Payment processed",
            payment_id=str(payment.id),
            order_id=str(order_id),
            status=new_status,
            gateway_reference=gateway_response.gateway_reference,
        )

        return ProcessPaymentResult(
            payment=payment,
            authorized=(new_status == PaymentStatus.AUTHORIZED.value),
            failure_reason=failure_reason,
        )

    # ── Refund (Saga compensating transaction) ────────────────────────────────

    async def process_refund(
        self,
        order_id: uuid.UUID,
        request: RefundRequest,
    ) -> Payment:
        """
        Issue a refund for a previously authorized payment.

        Called when the Saga needs to compensate for a downstream failure
        (e.g. delivery failed → trigger refund → REFUNDED state).

        Only AUTHORIZED payments can be refunded.
        """
        payment = await self._repo.get_by_order_id(order_id)
        if payment is None:
            raise PaymentNotFoundError(f"No payment found for order {order_id}")

        if payment.status not in (
            PaymentStatus.AUTHORIZED.value,
            PaymentStatus.PARTIALLY_REFUNDED.value,
        ):
            raise RefundNotAllowedError(
                f"Cannot refund payment in status {payment.status}"
            )

        refund_cents = request.amount_cents or payment.amount_cents
        if refund_cents > (payment.amount_cents - payment.refunded_amount_cents):
            raise RefundNotAllowedError(
                "Refund amount exceeds remaining authorized amount"
            )

        await self._gateway.refund(
            gateway_reference=f"payment-{payment.id}",
            amount_cents=refund_cents,
        )

        total_refunded = payment.refunded_amount_cents + refund_cents
        new_status = (
            PaymentStatus.REFUNDED.value
            if total_refunded >= payment.amount_cents
            else PaymentStatus.PARTIALLY_REFUNDED.value
        )

        updated = await self._repo.apply_refund(payment.id, refund_cents, new_status)
        logger.info(
            "Refund applied",
            payment_id=str(payment.id),
            order_id=str(order_id),
            refund_cents=refund_cents,
            new_status=new_status,
        )
        return updated

    # ── Reads ─────────────────────────────────────────────────────────────────

    async def get_payment_by_order(self, order_id: uuid.UUID) -> Payment:
        p = await self._repo.get_by_order_id(order_id)
        if p is None:
            raise PaymentNotFoundError(f"No payment found for order {order_id}")
        return p


# ── Helpers ───────────────────────────────────────────────────────────────────

def _to_cents(amount: Decimal) -> int:
    """Convert a Decimal dollar amount to integer cents."""
    return int((amount * 100).to_integral_value())
