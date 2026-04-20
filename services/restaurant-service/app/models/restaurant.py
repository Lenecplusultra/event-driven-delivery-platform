"""
services/restaurant-service/app/models/restaurant.py

SQLAlchemy ORM models for Restaurant Service.

Tables:
  - restaurants          Core restaurant record
  - menus                One menu per restaurant (extensible to many)
  - menu_items           Individual orderable items
  - order_confirmations  Audit log of confirm/reject decisions for incoming orders
"""

import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from libs.common.db.session import Base


def _utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)


class RestaurantStatus(str, enum.Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    PAUSED = "PAUSED"       # accepting no new orders temporarily


class OrderConfirmationDecision(str, enum.Enum):
    CONFIRMED = "CONFIRMED"
    REJECTED = "REJECTED"


class Restaurant(Base):
    __tablename__ = "restaurants"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=RestaurantStatus.CLOSED.value, index=True
    )
    address: Mapped[str] = mapped_column(String(500), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )

    menus: Mapped[list["Menu"]] = relationship(
        "Menu", back_populates="restaurant", cascade="all, delete-orphan", lazy="selectin"
    )

    def __repr__(self) -> str:
        return f"<Restaurant id={self.id} name={self.name!r} status={self.status}>"


class Menu(Base):
    __tablename__ = "menus"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    restaurant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("restaurants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False, default="Main Menu")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )

    restaurant: Mapped["Restaurant"] = relationship("Restaurant", back_populates="menus")
    items: Mapped[list["MenuItem"]] = relationship(
        "MenuItem", back_populates="menu", cascade="all, delete-orphan", lazy="selectin"
    )


class MenuItem(Base):
    __tablename__ = "menu_items"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    menu_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("menus.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    price: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    is_available: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, index=True
    )
    stock_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )

    menu: Mapped["Menu"] = relationship("Menu", back_populates="items")

    def __repr__(self) -> str:
        return f"<MenuItem id={self.id} name={self.name!r} available={self.is_available}>"


class OrderConfirmation(Base):
    """
    Audit log of every order confirm/reject decision made by this service.
    Used for idempotency checks and operational visibility.
    """

    __tablename__ = "order_confirmations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, unique=True, index=True
    )
    restaurant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    decision: Mapped[str] = mapped_column(String(16), nullable=False)   # CONFIRMED | REJECTED
    rejection_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_event_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    decided_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
