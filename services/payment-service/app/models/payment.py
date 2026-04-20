"""
services/payment-service/app/models/payment.py

SQLAlchemy ORM models for the Payment Service.

Tables:
  - payments           One payment record per order (idempotency enforced at this level)
  - payment_attempts   Every processing attempt including failures (full audit trail)
  - processed_events   Idempotency log — maps event_id → was processed
                       Prevents duplicate side effects if the same payment.requested
                       event is consumed more than once (retries, duplicates).

Design decision:
  The idempotency key is stored on the payment record itself.
  The processed_events table is a separate fast-lookup store checked BEFORE
  any business logic runs, so even a crash mid-processing is safe:
  if the payment was saved but the event not marked processed, the next
  attempt re-runs and the UNIQUE constraint on idempotency_key stops a
  duplicate payment from being inserted.
"""

import enum
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import ForeignKey

from libs.common.db.session import Base


def _utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)


class PaymentStatus(str, enum.Enum):
    PENDING = "PENDING"
    AUTHORIZED = "AUTHORIZED"
    FAILED = "FAILED"
    REFUNDED = "REFUNDED"
    PARTIALLY_REFUNDED = "PARTIALLY_REFUNDED"


class PaymentAttemptResult(str, enum.Enum):
    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"
    TIMEOUT = "TIMEOUT"


class Payment(Base):
    """
    One payment record per order. The (order_id, idempotency_key) pair
    is unique — any second write with the same key is a no-op.
    """
    __tablename__ = "payments"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, unique=True, index=True
    )
    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    idempotency_key: Mapped[str] = mapped_column(
        String(255), nullable=False, unique=True, index=True
    )
    amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="USD")
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=PaymentStatus.PENDING.value, index=True
    )
    failure_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # Tracks how much has been refunded (supports partial refund later)
    refunded_amount_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )

    attempts: Mapped[list["PaymentAttempt"]] = relationship(
        "PaymentAttempt",
        back_populates="payment",
        cascade="all, delete-orphan",
        order_by="PaymentAttempt.attempted_at",
    )

    def __repr__(self) -> str:
        return f"<Payment id={self.id} order={self.order_id} status={self.status}>"


class PaymentAttempt(Base):
    """
    Immutable record of every single processing attempt.
    Even failures and timeouts are logged here.
    Crucial for debugging and fraud detection.
    """
    __tablename__ = "payment_attempts"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    payment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("payments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    result: Mapped[str] = mapped_column(String(16), nullable=False)
    failure_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    gateway_reference: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )  # External payment gateway transaction ID (simulated here)
    processing_duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    attempted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    payment: Mapped["Payment"] = relationship("Payment", back_populates="attempts")


class ProcessedEvent(Base):
    """
    Fast-lookup idempotency store.
    Before processing any payment.requested event, check this table.
    If the event_id is already here, skip processing entirely.
    """
    __tablename__ = "processed_events"

    event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    processed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    outcome: Mapped[str] = mapped_column(String(32), nullable=False)  # AUTHORIZED | FAILED
