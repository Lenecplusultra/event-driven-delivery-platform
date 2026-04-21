"""
services/payment-service/app/core/config.py

Payment Service settings.
"""

from functools import lru_cache

from libs.common.config import BaseServiceSettings


class PaymentServiceSettings(BaseServiceSettings):
    service_name: str = "payment-service"
    kafka_consumer_group_id: str = "payment-service-group"

    # PostgreSQL
    database_url: str = (
        "postgresql+asyncpg://delivery:delivery_secret@payment-db:5432/payment_db"
    )

    # Topics this service publishes to
    topic_payment_authorized: str = "payment.authorized"
    topic_payment_failed: str = "payment.failed"
    topic_payment_refunded: str = "payment.refunded"

    # Topics this service consumes from
    topics_consume: list[str] = ["payment.requested"]

    # ── Simulation config ──────────────────────────────────────────────────────
    # Controls simulated payment behavior for local dev / demos.
    # In production these are replaced by real payment gateway integration.

    # 0.0 = always succeed, 1.0 = always fail
    simulated_failure_rate: float = 0.1

    # Simulated processing delay in seconds
    simulated_processing_delay: float = 0.3

    # Hard ceiling on a single transaction (cents, so 100000 = $1000.00)
    max_transaction_amount_cents: int = 100_000


@lru_cache
def get_settings() -> PaymentServiceSettings:
    return PaymentServiceSettings()
