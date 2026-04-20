"""
services/order-service/tests/unit/test_order_service.py

Unit tests for OrderService business logic.

Tests state machine transitions, idempotency, and error handling
using the in-memory SQLite test database.
"""

import uuid

import pytest
import pytest_asyncio

from app.models.order import Order, OrderStatus, VALID_TRANSITIONS
from app.repositories.order_repository import OrderRepository
from app.schemas.order import CreateOrderRequest, DeliveryAddressIn, OrderItemIn
from app.services.order_service import (
    DuplicateOrderError,
    InvalidStateTransitionError,
    OrderNotFoundError,
    OrderService,
)
from decimal import Decimal


@pytest.mark.asyncio
async def test_create_order_success(test_session, sample_order_payload):
    service = OrderService(test_session)
    request = CreateOrderRequest(**sample_order_payload)
    idempotency_key = str(uuid.uuid4())

    order = await service.create_order(request, idempotency_key)

    assert order.id is not None
    assert order.status == OrderStatus.PENDING_RESTAURANT_CONFIRMATION.value
    assert order.idempotency_key == idempotency_key
    assert len(order.items) == 1
    assert order.items[0].name == "Margherita Pizza"


@pytest.mark.asyncio
async def test_create_order_idempotency(test_session, sample_order_payload):
    """Duplicate request with same idempotency key returns existing order."""
    service = OrderService(test_session)
    request = CreateOrderRequest(**sample_order_payload)
    key = str(uuid.uuid4())

    original = await service.create_order(request, key)
    await test_session.commit()

    with pytest.raises(DuplicateOrderError) as exc_info:
        await service.create_order(request, key)

    assert exc_info.value.existing_order.id == original.id


@pytest.mark.asyncio
async def test_get_order_not_found(test_session):
    service = OrderService(test_session)
    with pytest.raises(OrderNotFoundError):
        await service.get_order(uuid.uuid4())


@pytest.mark.asyncio
async def test_valid_transitions_map_is_complete():
    """Sanity check: every happy-path event has an entry in VALID_TRANSITIONS."""
    expected_event_types = {
        "restaurant.order_confirmed",
        "restaurant.order_rejected",
        "payment.authorized",
        "payment.failed",
        "order.preparing",
        "order.ready_for_pickup",
        "driver.assigned",
        "delivery.picked_up",
        "delivery.completed",
        "delivery.failed",
    }
    actual_event_types = {et for (_, et) in VALID_TRANSITIONS.keys()}
    # All expected events should appear in the transitions map
    assert expected_event_types.issubset(actual_event_types)


@pytest.mark.asyncio
async def test_invalid_transition_raises(test_session, sample_order_payload):
    """Applying an out-of-sequence event raises InvalidStateTransitionError."""
    service = OrderService(test_session)
    request = CreateOrderRequest(**sample_order_payload)
    order = await service.create_order(request, str(uuid.uuid4()))
    await test_session.commit()

    # Order is PENDING_RESTAURANT_CONFIRMATION — cannot jump to delivery.completed
    with pytest.raises(InvalidStateTransitionError):
        await service.transition(
            order_id=order.id,
            event_type="delivery.completed",
            triggered_by="test",
        )
