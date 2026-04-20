"""
services/order-service/app/db/session.py

Order Service database initialization.

Calls libs.common.db.session.init_db() with this service's DATABASE_URL.
Also provides create_all() for local dev table creation (use Alembic in production).
"""

from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import get_settings
from app.models.order import Order, OrderItem, OrderStatusHistory, Outbox  # noqa: F401 — register models
from libs.common.db.session import Base, init_db


def init_order_db() -> None:
    """
    Initialize the async session factory for the Order Service.
    Call once from main.py lifespan startup.
    """
    settings = get_settings()
    init_db(settings.database_url)


async def create_tables() -> None:
    """
    Create all tables for local development.
    In staging/production, use Alembic migrations instead.
    """
    settings = get_settings()
    engine = create_async_engine(settings.database_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await engine.dispose()
