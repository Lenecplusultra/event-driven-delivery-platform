"""
services/dispatch-service/app/db/session.py
"""

from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import get_settings
from app.models.dispatch import DeliveryAssignment, Driver, ProcessedEvent  # noqa: F401
from libs.common.db.session import Base, init_db


def init_dispatch_db() -> None:
    settings = get_settings()
    init_db(settings.database_url)


async def create_tables() -> None:
    settings = get_settings()
    engine = create_async_engine(settings.database_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await engine.dispose()
