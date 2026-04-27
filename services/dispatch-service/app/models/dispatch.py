"""
services/dispatch-service/app/models/dispatch.py

Tables:
  - drivers               Driver registry with real-time status
  - delivery_assignments  One assignment record per order
  - processed_events      Idempotency log (same pattern as Payment Service)
"""

import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from libs.common.db.session import Base


def _utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)


class DriverStatus(str, enum.Enum):
    AVAILABLE = "AVAILABLE"
    ASSIGNED = "ASSIGNED"
    ON_DELIVERY = "ON_DELIVERY"
    OFFLINE = "OFFLINE"


class DeliveryStatus(str, enum.Enum):
    ASSIGNED = "ASSIGNED"
    PICKED_UP = "PICKED_UP"
    DELIVERED = "DELIVERED"
    FAILED = "FAILED"


class Driver(Base):
    __tablename__ = "drivers"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    zone: Mapped[str] = mapped_column(String(64), nullable=False, default="default", index=True)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=DriverStatus.AVAILABLE.value, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )

    assignments: Mapped[list["DeliveryAssignment"]] = relationship(
        "DeliveryAssignment", back_populates="driver"
    )

    def __repr__(self) -> str:
        return f"<Driver id={self.id} name={self.name!r} status={self.status}>"


class DeliveryAssignment(Base):
    """
    One record per order dispatch. Tracks the full delivery lifecycle
    from assignment through to completion or failure.
    """
    __tablename__ = "delivery_assignments"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, unique=True, index=True
    )
    driver_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("drivers.id"),
        nullable=False,
        index=True,
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=DeliveryStatus.ASSIGNED.value, index=True
    )
    failure_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    source_event_id: Mapped[str] = mapped_column(
        String(64), nullable=False, unique=True
    )
    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    picked_up_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    delivered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )

    driver: Mapped["Driver"] = relationship("Driver", back_populates="assignments")


class ProcessedEvent(Base):
    """Idempotency store — prevents double-processing dispatch.requested events."""
    __tablename__ = "processed_events"

    event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    processed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
