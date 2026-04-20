"""
services/order-service/app/models/order.py

SQLAlchemy ORM models for the Order Service.

Tables:
  - orders                 Core order record + state machine
  - order_items            Line items belonging to an order
  - order_status_history   Immutable audit log of every state transition
  - outbox                 Transactional outbox for reliable Kafka publication
"""

import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from libs.common.db.session import Base


def _utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)


# ── Order status enum ─────────────────────────────────────────────────────────


class OrderStatus(str, enum.Enum):
    CREATED = "CREATED"
    PENDING_RESTAURANT_CONFIRMATION = "PENDING_RESTAURANT_CONFIRMATION"
    RESTAURANT_CONFIRMED = "RESTAURANT_CONFIRMED"
    PAYMENT_PENDING = "PAYMENT_PENDING"
    PAYMENT_AUTHORIZED = "PAYMENT_AUTHORIZED"
    PREPARING = "PREPARING"
    READY_FOR_PICKUP = "READY_FOR_PICKUP"
    DRIVER_ASSIGNED = "DRIVER_ASSIGNED"
    OUT_FOR_DELIVERY = "OUT_FOR_DELIVERY"
    DELIVERED = "DELIVERED"
    # Failure / terminal
    RESTAURANT_REJECTED = "RESTAURANT_REJECTED"
    PAYMENT_FAILED = "PAYMENT_FAILED"
    CANCELLED = "CANCELLED"
    DELIVERY_FAILED = "DELIVERY_FAILED"
    REFUNDED = "REFUNDED"


# ── Valid state transitions ────────────────────────────────────────────────────
# Maps (current_status, event_type) → next_status
# Used by OrderService.transition() to validate and apply state changes.

VALID_TRANSITIONS: dict[tuple[str, str], OrderStatus] = {
    ("CREATED", "internal.confirm"):                          OrderStatus.PENDING_RESTAURANT_CONFIRMATION,
    ("PENDING_RESTAURANT_CONFIRMATION", "restaurant.order_confirmed"):  OrderStatus.RESTAURANT_CONFIRMED,
    ("PENDING_RESTAURANT_CONFIRMATION", "restaurant.order_rejected"):   OrderStatus.RESTAURANT_REJECTED,
    ("RESTAURANT_CONFIRMED", "internal.request_payment"):     OrderStatus.PAYMENT_PENDING,
    ("PAYMENT_PENDING", "payment.authorized"):                OrderStatus.PAYMENT_AUTHORIZED,
    ("PAYMENT_PENDING", "payment.failed"):                    OrderStatus.PAYMENT_FAILED,
    ("PAYMENT_AUTHORIZED", "order.preparing"):                OrderStatus.PREPARING,
    ("PREPARING", "order.ready_for_pickup"):                  OrderStatus.READY_FOR_PICKUP,
    ("READY_FOR_PICKUP", "driver.assigned"):                  OrderStatus.DRIVER_ASSIGNED,
    ("DRIVER_ASSIGNED", "delivery.picked_up"):                OrderStatus.OUT_FOR_DELIVERY,
    ("OUT_FOR_DELIVERY", "delivery.completed"):               OrderStatus.DELIVERED,
    ("OUT_FOR_DELIVERY", "delivery.failed"):                  OrderStatus.DELIVERY_FAILED,
    ("PAYMENT_FAILED", "internal.cancel"):                    OrderStatus.CANCELLED,
    ("DELIVERY_FAILED", "internal.refund"):                   OrderStatus.REFUNDED,
}


# ── ORM Models ────────────────────────────────────────────────────────────────


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    customer_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    restaurant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    status: Mapped[str] = mapped_column(
        String(64), nullable=False, default=OrderStatus.CREATED.value, index=True
    )
    correlation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, unique=True
    )
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    total_amount: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    delivery_address: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )

    items: Mapped[list["OrderItem"]] = relationship(
        "OrderItem", back_populates="order", cascade="all, delete-orphan", lazy="selectin"
    )
    status_history: Mapped[list["OrderStatusHistory"]] = relationship(
        "OrderStatusHistory", back_populates="order", cascade="all, delete-orphan",
        order_by="OrderStatusHistory.created_at"
    )

    def __repr__(self) -> str:
        return f"<Order id={self.id} status={self.status}>"


class OrderItem(Base):
    __tablename__ = "order_items"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, index=True
    )
    item_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_price: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    order: Mapped["Order"] = relationship("Order", back_populates="items")


class OrderStatusHistory(Base):
    __tablename__ = "order_status_history"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, index=True
    )
    previous_status: Mapped[str | None] = mapped_column(String(64), nullable=True)
    new_status: Mapped[str] = mapped_column(String(64), nullable=False)
    triggered_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    event_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    order: Mapped["Order"] = relationship("Order", back_populates="status_history")


class Outbox(Base):
    """
    Transactional outbox for reliable Kafka event publication.

    Written atomically with order state changes.
    A relay process reads unpublished records and sends them to Kafka.
    """
    __tablename__ = "outbox"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    event_type: Mapped[str] = mapped_column(String(128), nullable=False)
    topic: Mapped[str] = mapped_column(String(255), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    partition_key: Mapped[str | None] = mapped_column(String(255), nullable=True)   # order_id
    published: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
