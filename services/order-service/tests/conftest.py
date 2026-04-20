"""
services/order-service/tests/conftest.py

Shared pytest fixtures for Order Service tests.

Provides:
  - in-memory SQLite async engine for unit tests (no Postgres required)
  - AsyncClient for API integration tests
  - sample order request factory
"""

import uuid
from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.dependencies import get_db
from app.db.session import init_order_db
from app.main import app
from app.models.order import Order, OrderItem, OrderStatusHistory, Outbox  # noqa: F401
from libs.common.db.session import Base, init_db

# ── In-memory async SQLite for tests ──────────────────────────────────────────
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest_asyncio.fixture(scope="function")
async def test_engine():
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture(scope="function")
async def test_session(test_engine) -> AsyncGenerator[AsyncSession, None]:
    factory = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session


@pytest_asyncio.fixture(scope="function")
async def client(test_engine) -> AsyncGenerator[AsyncClient, None]:
    """AsyncClient with DB overridden to use the in-memory test engine."""
    factory = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)

    async def override_get_db():
        async with factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_db] = override_get_db

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac

    app.dependency_overrides.clear()


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def sample_order_payload() -> dict:
    return {
        "customer_id": str(uuid.uuid4()),
        "restaurant_id": str(uuid.uuid4()),
        "items": [
            {
                "item_id": str(uuid.uuid4()),
                "name": "Margherita Pizza",
                "quantity": 2,
                "unit_price": "12.50",
            }
        ],
        "delivery_address": {
            "street": "123 Main St",
            "city": "Atlanta",
            "state": "GA",
            "zip_code": "30301",
            "country": "US",
        },
    }
