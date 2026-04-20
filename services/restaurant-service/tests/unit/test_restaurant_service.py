"""
services/restaurant-service/tests/unit/test_restaurant_service.py
"""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.cache.menu_cache import MenuCache
from app.models.restaurant import (
    Menu,
    MenuItem,
    OrderConfirmation,
    OrderConfirmationDecision,
    Restaurant,
    RestaurantStatus,
)
from app.services.restaurant_service import RestaurantService
from app.schemas.restaurant import MenuCreate, MenuItemCreate, RestaurantCreate
from libs.common.db.session import Base

TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest_asyncio.fixture
async def test_session():
    engine = create_async_engine(TEST_DATABASE_URL)
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
    cache = MagicMock(spec=MenuCache)
    cache.get_menu = AsyncMock(return_value=None)
    cache.set_menu = AsyncMock()
    cache.invalidate_menu = AsyncMock()
    cache.get_items_availability_bulk = AsyncMock(return_value={})
    cache.set_item_availability = AsyncMock()
    cache.invalidate_item = AsyncMock()
    return cache


@pytest.mark.asyncio
async def test_create_restaurant(test_session, mock_cache):
    svc = RestaurantService(test_session, mock_cache)
    data = RestaurantCreate(
        name="Pizza Palace",
        address="123 Main St, Atlanta, GA",
        menu=MenuCreate(
            name="Main Menu",
            items=[
                MenuItemCreate(name="Margherita", price="12.99"),
                MenuItemCreate(name="Pepperoni", price="14.99"),
            ],
        ),
    )
    restaurant = await svc.create_restaurant(data)
    assert restaurant.id is not None
    assert restaurant.name == "Pizza Palace"
    assert restaurant.status == RestaurantStatus.CLOSED.value
    assert len(restaurant.menus) == 1
    assert len(restaurant.menus[0].items) == 2


@pytest.mark.asyncio
async def test_confirm_order_restaurant_closed(test_session, mock_cache):
    """Order confirmation is rejected when restaurant is closed."""
    svc = RestaurantService(test_session, mock_cache)

    # Create a CLOSED restaurant
    data = RestaurantCreate(name="Closed Cafe", address="1 St")
    restaurant = await svc.create_restaurant(data)
    await test_session.commit()

    item_id = uuid.uuid4()
    mock_cache.get_items_availability_bulk.return_value = {str(item_id): True}

    confirmation = await svc.confirm_order(
        order_id=uuid.uuid4(),
        restaurant_id=restaurant.id,
        item_ids=[item_id],
        source_event_id=str(uuid.uuid4()),
    )

    assert confirmation.decision == OrderConfirmationDecision.REJECTED.value
    assert "not open" in confirmation.rejection_reason


@pytest.mark.asyncio
async def test_confirm_order_items_unavailable(test_session, mock_cache):
    """Order confirmation is rejected when items are unavailable."""
    svc = RestaurantService(test_session, mock_cache)

    data = RestaurantCreate(name="Open Cafe", address="1 St")
    restaurant = await svc.create_restaurant(data)
    restaurant.status = RestaurantStatus.OPEN.value
    await test_session.commit()

    unavailable_item_id = uuid.uuid4()
    mock_cache.get_items_availability_bulk.return_value = {
        str(unavailable_item_id): False
    }

    confirmation = await svc.confirm_order(
        order_id=uuid.uuid4(),
        restaurant_id=restaurant.id,
        item_ids=[unavailable_item_id],
        source_event_id=str(uuid.uuid4()),
    )

    assert confirmation.decision == OrderConfirmationDecision.REJECTED.value
    assert "unavailable" in confirmation.rejection_reason


@pytest.mark.asyncio
async def test_menu_cache_miss_then_hit(test_session, mock_cache):
    """On cache miss, menu is fetched from DB and cached."""
    svc = RestaurantService(test_session, mock_cache)

    data = RestaurantCreate(name="Cached Bistro", address="5 Ave")
    restaurant = await svc.create_restaurant(data)
    await test_session.commit()

    # Cache miss → DB fetch → cache population
    result = await svc.get_menu_cached(restaurant.id)

    assert result["id"] == str(restaurant.id)
    mock_cache.set_menu.assert_called_once()
