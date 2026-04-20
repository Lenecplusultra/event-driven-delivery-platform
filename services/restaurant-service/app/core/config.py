"""
services/restaurant-service/app/core/config.py

Restaurant Service settings.
"""

from functools import lru_cache

from libs.common.config import BaseServiceSettings


class RestaurantServiceSettings(BaseServiceSettings):
    service_name: str = "restaurant-service"
    kafka_consumer_group_id: str = "restaurant-service-group"

    # PostgreSQL
    database_url: str = (
        "postgresql+asyncpg://delivery:delivery_secret@localhost:5438/restaurant_db"
    )

    # Redis TTLs (seconds)
    redis_menu_ttl: int = 300           # 5 min — full restaurant menu
    redis_item_avail_ttl: int = 120     # 2 min — individual item availability

    # Topics this service publishes to
    topic_order_confirmed: str = "restaurant.order_confirmed"
    topic_order_rejected: str = "restaurant.order_rejected"
    topic_order_preparing: str = "order.preparing"
    topic_order_ready: str = "order.ready_for_pickup"

    # Topics this service consumes from
    topics_consume: list[str] = ["order.created"]

    # Simulate auto-confirm orders for local dev (no human operator needed)
    auto_confirm_orders: bool = True
    auto_confirm_delay_seconds: float = 0.5


@lru_cache
def get_settings() -> RestaurantServiceSettings:
    return RestaurantServiceSettings()
