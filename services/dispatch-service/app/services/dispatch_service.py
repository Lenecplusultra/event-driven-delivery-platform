"""
services/dispatch-service/app/services/dispatch_service.py

Business logic for Dispatch Service.

Responsibilities:
  - Assign the best available driver from Redis cache (DB fallback)
  - Record the assignment atomically with the idempotency mark
  - Update driver status in DB + invalidate Redis cache
  - Return assignment result for consumer to publish

Driver selection strategy (Phase 1):
  Longest-idle first — the driver who has been AVAILABLE the longest
  gets the next order. Ordered by updated_at ASC in the DB query.
"""

import random
import uuid
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.cache.driver_cache import DriverCache
from app.models.dispatch import DeliveryAssignment, DeliveryStatus, Driver, DriverStatus
from app.repositories.dispatch_repository import DispatchRepository
from libs.common.logging import get_logger

logger = get_logger(__name__)


class NoDriverAvailableError(Exception):
    pass


class AssignmentNotFoundError(Exception):
    pass


class DispatchService:
    def __init__(self, session: AsyncSession, cache: DriverCache) -> None:
        self._repo = DispatchRepository(session)
        self._cache = cache

    async def assign_driver(
        self,
        order_id: uuid.UUID,
        source_event_id: str,
        zone: str = "default",
    ) -> DeliveryAssignment:
        """
        Assign an available driver to the order.

        Idempotent: if an assignment already exists for this order,
        return it unchanged.

        Strategy:
          1. Check Redis pool for available drivers in zone
          2. On miss: query DB, repopulate cache
          3. Pick first (longest-idle) driver
          4. Mark driver ASSIGNED in DB
          5. Invalidate Redis pool
          6. Create DeliveryAssignment record
          7. Mark event processed
        """
        # ── Idempotency ────────────────────────────────────────────────────────
        if await self._repo.is_event_processed(source_event_id):
            existing = await self._repo.get_assignment_by_order(order_id)
            if existing:
                logger.info(
                    "Duplicate dispatch.requested — returning existing assignment",
                    order_id=str(order_id),
                )
                return existing

        # ── Find available driver ──────────────────────────────────────────────
        driver = await self._pick_driver(zone)
        if driver is None:
            raise NoDriverAvailableError(
                f"No available drivers in zone '{zone}' for order {order_id}"
            )

        # ── Mark driver as assigned ────────────────────────────────────────────
        await self._repo.update_driver_status(driver.id, DriverStatus.ASSIGNED.value)
        await self._cache.set_driver_status(driver.id, DriverStatus.ASSIGNED.value)
        await self._cache.invalidate_pool(zone)

        # ── Create assignment record ───────────────────────────────────────────
        assignment = DeliveryAssignment(
            order_id=order_id,
            driver_id=driver.id,
            status=DeliveryStatus.ASSIGNED.value,
            source_event_id=source_event_id,
        )
        assignment = await self._repo.create_assignment(assignment)
        await self._repo.mark_event_processed(source_event_id)

        logger.info(
            "Driver assigned",
            order_id=str(order_id),
            driver_id=str(driver.id),
            driver_name=driver.name,
            zone=zone,
        )
        return assignment

    async def record_pickup(self, order_id: uuid.UUID) -> DeliveryAssignment:
        assignment = await self._repo.get_assignment_by_order(order_id)
        if assignment is None:
            raise AssignmentNotFoundError(f"No assignment for order {order_id}")

        await self._repo.update_driver_status(
            assignment.driver_id, DriverStatus.ON_DELIVERY.value
        )
        updated = await self._repo.update_assignment_status(
            order_id=order_id,
            status=DeliveryStatus.PICKED_UP.value,
            picked_up_at=datetime.now(tz=timezone.utc),
        )
        logger.info("Delivery picked up", order_id=str(order_id))
        return updated

    async def record_delivery(self, order_id: uuid.UUID) -> DeliveryAssignment:
        assignment = await self._repo.get_assignment_by_order(order_id)
        if assignment is None:
            raise AssignmentNotFoundError(f"No assignment for order {order_id}")

        # Driver is now available again
        await self._repo.update_driver_status(
            assignment.driver_id, DriverStatus.AVAILABLE.value
        )
        await self._cache.set_driver_status(assignment.driver_id, DriverStatus.AVAILABLE.value)
        await self._cache.invalidate_pool("default")

        updated = await self._repo.update_assignment_status(
            order_id=order_id,
            status=DeliveryStatus.DELIVERED.value,
            delivered_at=datetime.now(tz=timezone.utc),
        )
        logger.info("Delivery completed", order_id=str(order_id))
        return updated

    async def record_failure(self, order_id: uuid.UUID, reason: str) -> DeliveryAssignment:
        assignment = await self._repo.get_assignment_by_order(order_id)
        if assignment is None:
            raise AssignmentNotFoundError(f"No assignment for order {order_id}")

        # Return driver to available pool
        await self._repo.update_driver_status(
            assignment.driver_id, DriverStatus.AVAILABLE.value
        )
        await self._cache.set_driver_status(assignment.driver_id, DriverStatus.AVAILABLE.value)
        await self._cache.invalidate_pool("default")

        updated = await self._repo.update_assignment_status(
            order_id=order_id,
            status=DeliveryStatus.FAILED.value,
            failure_reason=reason,
        )
        logger.warning("Delivery failed", order_id=str(order_id), reason=reason)
        return updated

    async def get_assignment(self, order_id: uuid.UUID) -> DeliveryAssignment:
        a = await self._repo.get_assignment_by_order(order_id)
        if a is None:
            raise AssignmentNotFoundError(f"No assignment for order {order_id}")
        return a

    # ── Driver selection ──────────────────────────────────────────────────────

    async def _pick_driver(self, zone: str) -> Driver | None:
        """
        Return the longest-idle available driver.
        Cache-first: if Redis pool has IDs, pick the first one and verify
        it's still AVAILABLE in DB (TTL means it should be).
        """
        # Try cache first
        cached_ids = await self._cache.get_available_drivers(zone)
        if cached_ids:
            driver_id = uuid.UUID(cached_ids[0])
            driver = await self._repo.get_driver_by_id(driver_id)
            if driver and driver.status == DriverStatus.AVAILABLE.value:
                return driver
            # Cache stale — fall through to DB
            await self._cache.invalidate_pool(zone)

        # DB query — returns longest-idle first
        drivers = await self._repo.get_available_drivers(zone)
        if not drivers:
            return None

        # Repopulate cache
        await self._cache.set_available_drivers(zone, [str(d.id) for d in drivers])
        return drivers[0]

    # ── Driver seeding (local dev) ────────────────────────────────────────────

    async def seed_drivers(self, count: int = 10) -> list[Driver]:
        """Create simulated drivers for local dev if none exist."""
        existing = await self._repo.get_available_drivers("default")
        if existing:
            logger.info("Drivers already seeded", count=len(existing))
            return existing

        names = [
            "Alex Rivera", "Jordan Lee", "Sam Chen", "Morgan Davis",
            "Taylor Kim", "Casey Brown", "Riley Patel", "Jamie Wilson",
            "Drew Martinez", "Quinn Thompson",
        ]
        drivers = []
        for i in range(min(count, len(names))):
            driver = Driver(
                name=names[i],
                phone=f"+1404555{i:04d}",
                zone="default",
                status=DriverStatus.AVAILABLE.value,
            )
            created = await self._repo.create_driver(driver)
            drivers.append(created)

        logger.info("Drivers seeded", count=len(drivers))
        return drivers
