"""
libs/common/logging.py

Structured JSON logging for all services.

Every log line includes:
  - timestamp
  - level
  - service
  - correlation_id  (pulled from contextvars, set at request/event ingestion)
  - trace_id        (pulled from active OTEL span when available)
  - span_id
  - message
  - extra fields passed as kwargs

Usage:
    from libs.common.logging import get_logger
    logger = get_logger(__name__)
    logger.info("Order created", order_id=str(order.id), status=order.status)
"""

import logging
import sys
from contextvars import ContextVar
from typing import Any

import structlog
from opentelemetry import trace

# ── Context variable for correlation_id ──────────────────────────────────────
# Set this at the start of every HTTP request and Kafka message handler.
correlation_id_ctx: ContextVar[str] = ContextVar("correlation_id", default="")
causation_id_ctx: ContextVar[str] = ContextVar("causation_id", default="")


def _add_otel_context(
    logger: Any, method: str, event_dict: dict
) -> dict:
    """Inject active OpenTelemetry trace/span IDs into every log record."""
    span = trace.get_current_span()
    if span and span.is_recording():
        ctx = span.get_span_context()
        event_dict["trace_id"] = format(ctx.trace_id, "032x")
        event_dict["span_id"] = format(ctx.span_id, "016x")
    return event_dict


def _add_correlation_ids(
    logger: Any, method: str, event_dict: dict
) -> dict:
    """Inject correlation_id and causation_id from context vars."""
    if cid := correlation_id_ctx.get():
        event_dict["correlation_id"] = cid
    if causation := causation_id_ctx.get():
        event_dict["causation_id"] = causation
    return event_dict


def configure_logging(service_name: str, log_level: str = "INFO") -> None:
    """
    Call once at application startup (in main.py lifespan).
    Sets up structlog with JSON rendering for production and
    pretty console rendering for local development.
    """
    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        _add_correlation_ids,
        _add_otel_context,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    structlog.configure(
        processors=shared_processors
        + [
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        processor=structlog.processors.JSONRenderer(),
        foreign_pre_chain=shared_processors,
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.handlers = [handler]
    root_logger.setLevel(log_level.upper())

    # Silence noisy third-party loggers
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("aiokafka").setLevel(logging.WARNING)


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Return a structlog logger bound to the given name."""
    return structlog.get_logger(name)
