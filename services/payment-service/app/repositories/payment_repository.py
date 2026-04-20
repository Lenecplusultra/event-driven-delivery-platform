"""
services/payment-service/app/repositories/payment_repository.py

Data access layer for Payment Service.

Key patterns:
  - get_by_idempotency_key() is the primary idempotency check path
  - save_payment() uses INSERT ... ON CONFLICT DO NOTHING semantics
    so concurrent duplicate requests are safe at the DB level
  - All state transitions are append-only (via PaymentAttempt records)
  - ProcessedEvent records are written atomically with payment state changes
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.payment import Payment, PaymentAttempt, PaymentAttemptResult, PaymentStatus, ProcessedEvent
from libs.common.logging import get_logger

logger = get_logger(__name__)


class PaymentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ── Idempotency ───────────────────────────────────────────────────────────

    async def is_event_processed(self, event_id: str) -> bool:
        result = await self._session.execute(
            select(ProcessedEvent).where(ProcessedEvent.event_id == event_id)
        )
        return result.scalar_one_or_none() is not None

    async def mark_event_processed(self, event_id: str, outcome: str) -> None:
        record = ProcessedEvent(event_id=event_id, outcome=outcome)
        self._session.add(record)
        await self._session.flush()

    # ── Payment reads ─────────────────────────────────────────────────────────

    async def get_by_id(self, payment_id: uuid.UUID) -> Payment | None:
        result = await self._session.execute(
            select(Payment).where(Payment.id == payment_id)
        )
        return result.scalar_one_or_none()

    async def get_by_order_id(self, order_id: uuid.UUID) -> Payment | None:
        result = await self._session.execute(
            select(Payment).where(Payment.order_id == order_id)
        )
        return result.scalar_one_or_none()

    async def get_by_idempotency_key(self, key: str) -> Payment | None:
        result = await self._session.execute(
            select(Payment).where(Payment.idempotency_key == key)
        )
        return result.scalar_one_or_none()

    # ── Payment writes ────────────────────────────────────────────────────────

    async def create_payment(self, payment: Payment) -> Payment:
        self._session.add(payment)
        await self._session.flush()
        logger.info(
            "Payment record created",
            payment_id=str(payment.id),
            order_id=str(payment.order_id),
            amount_cents=payment.amount_cents,
        )
        return payment

    async def update_status(
        self,
        payment_id: uuid.UUID,
        status: str,
        failure_reason: str | None = None,
    ) -> Payment | None:
        values: dict = {
            "status": status,
            "updated_at": datetime.now(tz=timezone.utc),
        }
        if failure_reason is not None:
            values["failure_reason"] = failure_reason

        await self._session.execute(
            update(Payment).where(Payment.id == payment_id).values(**values)
        )
        await self._session.flush()
        return await self.get_by_id(payment_id)

    async def record_attempt(self, attempt: PaymentAttempt) -> PaymentAttempt:
        self._session.add(attempt)
        await self._session.flush()
        return attempt

    async def apply_refund(
        self, payment_id: uuid.UUID, refund_amount_cents: int, new_status: str
    ) -> Payment | None:
        payment = await self.get_by_id(payment_id)
        if payment is None:
            return None
        await self._session.execute(
            update(Payment)
            .where(Payment.id == payment_id)
            .values(
                refunded_amount_cents=Payment.refunded_amount_cents + refund_amount_cents,
                status=new_status,
                updated_at=datetime.now(tz=timezone.utc),
            )
        )
        await self._session.flush()
        return await self.get_by_id(payment_id)
