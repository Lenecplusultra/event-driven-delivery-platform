"""
services/dispatch-service/app/repositories/dispatch_repository.py
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.dispatch import (
    DeliveryAssignment,
    DeliveryStatus,
    Driver,
    DriverStatus,
    ProcessedEvent,
)
from libs.common.logging import get_logger

logger = get_logger(__name__)


class DispatchRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ── Idempotency ───────────────────────────────────────────────────────────

    async def is_event_processed(self, event_id: str) -> bool:
        result = await self._session.execute(
            select(ProcessedEvent).where(ProcessedEvent.event_id == event_id)
        )
        return result.scalar_one_or_none() is not None

    async def mark_event_processed(self, event_id: str) -> None:
        self._session.add(ProcessedEvent(event_id=event_id))
        await self._session.flush()

    # ── Driver reads ──────────────────────────────────────────────────────────

    async def get_available_drivers(self, zone: str = "default") -> list[Driver]:
        result = await self._session.execute(
            select(Driver)
            .where(Driver.status == DriverStatus.AVAILABLE.value)
            .where(Driver.zone == zone)
            .order_by(Driver.updated_at)   # longest-idle first
        )
        return list(result.scalars().all())

    async def get_driver_by_id(self, driver_id: uuid.UUID) -> Driver | None:
        result = await self._session.execute(
            select(Driver).where(Driver.id == driver_id)
        )
        return result.scalar_one_or_none()

    # ── Driver writes ─────────────────────────────────────────────────────────

    async def create_driver(self, driver: Driver) -> Driver:
        self._session.add(driver)
        await self._session.flush()
        return driver

    async def update_driver_status(self, driver_id: uuid.UUID, status: str) -> None:
        await self._session.execute(
            update(Driver)
            .where(Driver.id == driver_id)
            .values(status=status, updated_at=datetime.now(tz=timezone.utc))
        )
        await self._session.flush()

    # ── Assignment reads ──────────────────────────────────────────────────────

    async def get_assignment_by_order(self, order_id: uuid.UUID) -> DeliveryAssignment | None:
        result = await self._session.execute(
            select(DeliveryAssignment)
            .options(selectinload(DeliveryAssignment.driver))
            .where(DeliveryAssignment.order_id == order_id)
        )
        return result.scalar_one_or_none()

    # ── Assignment writes ─────────────────────────────────────────────────────

    async def create_assignment(self, assignment: DeliveryAssignment) -> DeliveryAssignment:
        self._session.add(assignment)
        await self._session.flush()
        return assignment

    async def update_assignment_status(
        self,
        order_id: uuid.UUID,
        status: str,
        failure_reason: str | None = None,
        picked_up_at: datetime | None = None,
        delivered_at: datetime | None = None,
    ) -> DeliveryAssignment | None:
        values: dict = {
            "status": status,
            "updated_at": datetime.now(tz=timezone.utc),
        }
        if failure_reason:
            values["failure_reason"] = failure_reason
        if picked_up_at:
            values["picked_up_at"] = picked_up_at
        if delivered_at:
            values["delivered_at"] = delivered_at

        await self._session.execute(
            update(DeliveryAssignment)
            .where(DeliveryAssignment.order_id == order_id)
            .values(**values)
        )
        await self._session.flush()
        return await self.get_assignment_by_order(order_id)
