"""
libs/common/tracing.py

OpenTelemetry setup for all services.

Sets up:
  - OTLP gRPC trace exporter
  - Resource with service.name, environment
  - Span helpers for Kafka producer/consumer instrumentation
  - Utility to extract/inject correlation IDs into spans

Usage:
    from libs.common.tracing import configure_tracing, get_tracer, span_from_event

    # In main.py lifespan:
    configure_tracing(settings.service_name, settings.otel_exporter_otlp_endpoint)

    # In a Kafka consumer:
    with span_from_event("process_order_created", event) as span:
        span.set_attribute("order.id", event.aggregate_id)
        ...
"""

from contextlib import contextmanager
from typing import Generator

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.redis import RedisInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from libs.common.schemas.base_event import BaseEvent

_tracer: trace.Tracer | None = None


def configure_tracing(service_name: str, otlp_endpoint: str) -> None:
    """
    Initialize the global TracerProvider.
    Call once at application startup before the FastAPI app starts accepting requests.
    """
    global _tracer

    resource = Resource.create({"service.name": service_name})
    exporter = OTLPSpanExporter(endpoint=otlp_endpoint, insecure=True)
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)

    # Auto-instrument HTTP, DB, and Redis
    FastAPIInstrumentor().instrument()
    SQLAlchemyInstrumentor().instrument()
    RedisInstrumentor().instrument()

    _tracer = trace.get_tracer(service_name)


def get_tracer() -> trace.Tracer:
    """Return the configured tracer. Must call configure_tracing() first."""
    if _tracer is None:
        raise RuntimeError(
            "Tracer not configured. Call configure_tracing() at application startup."
        )
    return _tracer


@contextmanager
def span_from_event(
    operation_name: str, event: BaseEvent
) -> Generator[trace.Span, None, None]:
    """
    Context manager that creates a span for Kafka event processing.

    Automatically sets:
      - correlation_id
      - causation_id
      - event.type
      - event.id
      - aggregate.type
      - aggregate.id
      - producer (the emitting service)
    """
    tracer = get_tracer()
    with tracer.start_as_current_span(operation_name) as span:
        span.set_attribute("correlation_id", event.correlation_id)
        span.set_attribute("causation_id", event.causation_id or "")
        span.set_attribute("event.type", event.event_type)
        span.set_attribute("event.id", event.event_id)
        span.set_attribute("aggregate.type", event.aggregate_type)
        span.set_attribute("aggregate.id", event.aggregate_id)
        span.set_attribute("event.producer", event.producer)
        yield span


@contextmanager
def kafka_producer_span(
    topic: str, event_type: str, correlation_id: str
) -> Generator[trace.Span, None, None]:
    """
    Context manager that creates a span for Kafka event publishing.
    """
    tracer = get_tracer()
    with tracer.start_as_current_span(f"kafka.publish.{event_type}") as span:
        span.set_attribute("messaging.system", "kafka")
        span.set_attribute("messaging.destination", topic)
        span.set_attribute("messaging.operation", "publish")
        span.set_attribute("correlation_id", correlation_id)
        span.set_attribute("event.type", event_type)
        yield span
