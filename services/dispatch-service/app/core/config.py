"""
services/dispatch-service/app/core/config.py
"""

from functools import lru_cache
from libs.common.config import BaseServiceSettings


class DispatchServiceSettings(BaseServiceSettings):
    service_name: str = "dispatch-service"
    kafka_consumer_group_id: str = "dispatch-service-group"

    database_url: str = (
        "postgresql+asyncpg://delivery:delivery_secret@dispatch-db:5432/dispatch_db"
    )

    topic_driver_assigned: str = "driver.assigned"
    topic_delivery_picked_up: str = "delivery.picked_up"
    topic_delivery_completed: str = "delivery.completed"
    topic_delivery_failed: str = "delivery.failed"

    topics_consume: list[str] = ["dispatch.requested"]

    redis_driver_status_ttl: int = 30
    redis_driver_pool_ttl: int = 10

    simulated_driver_count: int = 10
    simulated_pickup_delay: float = 2.0
    simulated_delivery_delay: float = 4.0
    simulated_delivery_failure_rate: float = 0.05


@lru_cache
def get_settings() -> DispatchServiceSettings:
    return DispatchServiceSettings()
