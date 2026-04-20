"""
libs/common/config.py

Base Pydantic Settings class inherited by every service's config.
Each service extends BaseServiceSettings and adds its own fields.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class BaseServiceSettings(BaseSettings):
    """
    Shared configuration fields present in every service.
    Services extend this and add service-specific fields.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Service identity ──────────────────────────────────────────────
    service_name: str = "unset-service"
    environment: str = "local"      # local | staging | production
    log_level: str = "INFO"

    # ── Kafka ─────────────────────────────────────────────────────────
    kafka_bootstrap_servers: str = "localhost:9092"
    kafka_consumer_group_id: str = "unset-consumer-group"

    # ── Redis ─────────────────────────────────────────────────────────
    redis_url: str = "redis://localhost:6379/0"

    # ── OpenTelemetry ─────────────────────────────────────────────────
    otel_exporter_otlp_endpoint: str = "http://localhost:4317"
    otel_traces_enabled: bool = True
    otel_metrics_enabled: bool = True
