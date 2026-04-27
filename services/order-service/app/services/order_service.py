"""
services/order-service/app/services/order_service.py

Business logic layer for Order Service.

Responsibilities:
  - Validate new order requests
  - Apply state machine transitions (using VALID_TRANSITIONS map)
  - Write state changes + outbox records atomically via OrderRepository
  - Never call Kafka producer directly — uses outbox pattern
  - Raise domain exceptions for invalid transitions or not-found orders

This layer sits between the API/consumer layer and the repository layer.
It has no knowledge of HTTP or Kafka — only domain logic.
"""

import uuid
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.order import Order, OrderItem, OrderStatus, VALID_TRANSITIONS
from app.repositories.order_repository import OrderRepository
from app.schemas.order import CreateOrderRequest
from libs.common.logging import get_logger
from libs.common.schemas.base_event import BaseEvent
from libs.contracts.events.order_events import (
    make_dispatch_requested,
    make_order_created,
    make_payment_requested,
)

logger = get_logger(__name__)


class InvalidStateTransitionError(Exception):
    """Raised when an event triggers a transition not allowed from the current state."""
    pass


class OrderNotFoundError(Exception):
    pass


class DuplicateOrderError(Exception):
    """Raised when an order with the same idempotency key already exists."""
    def __init__(self, existing_order: Order) -> None:
        self.existing_order = existing_order
        super().__init__(f"Order with this idempotency key already exists: {existing_order.id}")


class OrderService:
    def __init__(self, session: AsyncSession) -> None:
        self._repo = OrderRepository(session)

    # ── Create ────────────────────────────────────────────────────────────────

    async def create_order(
        self,
        request: CreateOrderRequest,
        idempotency_key: str,
    ) -> Order:
        """
        Create a new order.

        Idempotency: if an order with this key already exists, return it unchanged.
        Otherwise, persist the order + items + order.created outbox record atomically.
        """
        # ── Idempotency check ─────────────────────────────────────────────────
        existing = await self._repo.get_by_idempotency_key(idempotency_key)
        if existing:
            logger.info(
                "Returning existing order for idempotency key",
                idempotency_key=idempotency_key,
                order_id=str(existing.id),
            )
            raise DuplicateOrderError(existing)

        order_id = uuid.uuid4()
        correlation_id = order_id   # correlation_id == order_id for order-centric events

        order = Order(
            id=order_id,
            customer_id=request.customer_id,
            restaurant_id=request.restaurant_id,
            status=OrderStatus.PENDING_RESTAURANT_CONFIRMATION.value,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            total_amount=float(request.total_amount),
            delivery_address=request.delivery_address.model_dump(),
        )

        items = [
            OrderItem(
                order_id=order_id,
                item_id=item.item_id,
                name=item.name,
                quantity=item.quantity,
                unit_price=float(item.unit_price),
            )
            for item in request.items
        ]

        outbox_event = make_order_created(
            order_id=str(order_id),
            customer_id=str(request.customer_id),
            restaurant_id=str(request.restaurant_id),
            items=[
                {
                    "item_id": str(i.item_id),
                    "name": i.name,
                    "quantity": i.quantity,
                    "unit_price": str(i.unit_price),
                }
                for i in request.items
            ],
            total_amount=request.total_amount,
            delivery_address=request.delivery_address.model_dump(),
            idempotency_key=idempotency_key,
        )

        created = await self._repo.create(
            order=order,
            items=items,
            outbox_event=outbox_event,
            topic="order.created",
        )

        logger.info(
            "Order created",
            order_id=str(order_id),
            customer_id=str(request.customer_id),
            restaurant_id=str(request.restaurant_id),
            total_amount=str(request.total_amount),
        )
        return created

    # ── State machine transitions ─────────────────────────────────────────────

    async def transition(
        self,
        order_id: uuid.UUID,
        event_type: str,
        triggered_by: str,
        causation_event_id: str | None = None,
        extra_payload: dict | None = None,
    ) -> Order:
        """
        Apply a state transition driven by an incoming domain event.

        Validates the (current_status, event_type) pair against VALID_TRANSITIONS.
        Writes the new status + optional follow-up outbox event atomically.
        """
        order = await self._repo.get_by_id(order_id)
        if order is None:
            raise OrderNotFoundError(f"Order {order_id} not found")

        transition_key = (order.status, event_type)
        new_status = VALID_TRANSITIONS.get(transition_key)

        if new_status is None:
            raise InvalidStateTransitionError(
                f"No valid transition from '{order.status}' on event '{event_type}'"
            )

        # ── Build follow-up outbox event if required by the new state ─────────
        followup_event, followup_topic = self._followup_event(order, new_status, extra_payload, causation_event_id)

        updated = await self._repo.transition_status(
            order_id=order.id,
            new_status=new_status.value,
            triggered_by=triggered_by,
            event_id=uuid.UUID(causation_event_id) if causation_event_id else None,
            outbox_event=followup_event,
            topic=followup_topic,
        )

        logger.info(
            "Order transitioned",
            order_id=str(order_id),
            previous_status=order.status,
            new_status=new_status.value,
            event_type=event_type,
        )
        return updated

    def _followup_event(
        self,
        order: Order,
        new_status: OrderStatus,
        extra_payload: dict | None,
        causation_event_id: str | None,
    ) -> tuple[BaseEvent | None, str | None]:
        """
        When a transition lands in a state that requires the Order Service
        to emit a follow-up command event, build that event here.

        Returns (event, topic) or (None, None).
        """
        extra = extra_payload or {}

        if new_status == OrderStatus.RESTAURANT_CONFIRMED:
            # Immediately request payment after restaurant confirms
            event = make_payment_requested(
                order_id=str(order.id),
                customer_id=str(order.customer_id),
                amount=Decimal(str(order.total_amount)),
                idempotency_key=f"payment-{order.id}",
                causation_id=causation_event_id,
            )
            return event, "payment.requested"

        if new_status == OrderStatus.READY_FOR_PICKUP:
            # Request dispatch when order is ready for pickup
            event = make_dispatch_requested(
                order_id=str(order.id),
                restaurant_id=str(order.restaurant_id),
                delivery_address=order.delivery_address,
                causation_id=causation_event_id,
            )
            return event, "dispatch.requested"

        return None, None

    # ── Reads ─────────────────────────────────────────────────────────────────

    async def get_order(self, order_id: uuid.UUID) -> Order:
        order = await self._repo.get_by_id(order_id)
        if order is None:
            raise OrderNotFoundError(f"Order {order_id} not found")
        return order
    
    async def get_order_history(self, order_id: uuid.UUID):
        return await self._repo.get_order_history(order_id)
