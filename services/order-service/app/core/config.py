"""
services/order-service/app/core/config.py

Order Service settings. Extends BaseServiceSettings with service-specific fields.
All values are loaded from environment variables / .env file.
"""

from functools import lru_cache

from libs.common.config import BaseServiceSettings


class OrderServiceSettings(BaseServiceSettings):
    service_name: str = "order-service"
    kafka_consumer_group_id: str = "order-service-group"

    # PostgreSQL
    database_url: str = "postgresql+asyncpg://delivery:delivery_secret@order-db:5432/order_db"

    # Topics this service publishes to
    topic_order_created: str = "order.created"
    topic_payment_requested: str = "payment.requested"
    topic_dispatch_requested: str = "dispatch.requested"

    # Topics this service consumes from
    topics_consume: list[str] = [
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
    ]


@lru_cache
def get_settings() -> OrderServiceSettings:
    return OrderServiceSettings()
