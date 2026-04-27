"""
services/dispatch-service/tests/unit/test_dispatch_service.py
"""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.cache.driver_cache import DriverCache
from app.models.dispatch import DeliveryStatus, Driver, DriverStatus
from app.services.dispatch_service import DispatchService, NoDriverAvailableError
from libs.common.db.session import Base

TEST_DB = "sqlite+aiosqlite:///:memory:"


@pytest_asyncio.fixture
async def test_session():
    engine = create_async_engine(TEST_DB)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.fixture
def mock_cache():
    cache = MagicMock(spec=DriverCache)
    cache.get_available_drivers = AsyncMock(return_value=None)
    cache.set_available_drivers = AsyncMock()
    cache.set_driver_status = AsyncMock()
    cache.invalidate_pool = AsyncMock()
    return cache


@pytest.mark.asyncio
async def test_seed_and_assign_driver(test_session, mock_cache):
    svc = DispatchService(test_session, mock_cache)

    # Seed drivers
    drivers = await svc.seed_drivers(3)
    assert len(drivers) == 3
    await test_session.commit()

    # Assign
    order_id = uuid.uuid4()
    assignment = await svc.assign_driver(
        order_id=order_id,
        source_event_id=str(uuid.uuid4()),
    )

    assert assignment.order_id == order_id
    assert assignment.status == DeliveryStatus.ASSIGNED.value
    mock_cache.invalidate_pool.assert_called_once()


@pytest.mark.asyncio
async def test_no_driver_raises(test_session, mock_cache):
    svc = DispatchService(test_session, mock_cache)

    with pytest.raises(NoDriverAvailableError):
        await svc.assign_driver(
            order_id=uuid.uuid4(),
            source_event_id=str(uuid.uuid4()),
        )


@pytest.mark.asyncio
async def test_idempotent_assignment(test_session, mock_cache):
    svc = DispatchService(test_session, mock_cache)
    await svc.seed_drivers(2)
    await test_session.commit()

    order_id = uuid.uuid4()
    event_id = str(uuid.uuid4())

    a1 = await svc.assign_driver(order_id=order_id, source_event_id=event_id)
    await test_session.commit()

    # Same event_id again — should return existing
    a2 = await svc.assign_driver(order_id=order_id, source_event_id=event_id)
    assert a1.id == a2.id


@pytest.mark.asyncio
async def test_full_delivery_lifecycle(test_session, mock_cache):
    svc = DispatchService(test_session, mock_cache)
    await svc.seed_drivers(2)
    await test_session.commit()

    order_id = uuid.uuid4()
    assignment = await svc.assign_driver(
        order_id=order_id, source_event_id=str(uuid.uuid4())
    )
    await test_session.commit()
    assert assignment.status == DeliveryStatus.ASSIGNED.value

    picked = await svc.record_pickup(order_id)
    assert picked.status == DeliveryStatus.PICKED_UP.value
    assert picked.picked_up_at is not None

    delivered = await svc.record_delivery(order_id)
    assert delivered.status == DeliveryStatus.DELIVERED.value
    assert delivered.delivered_at is not None
