"""
services/order-service/app/main.py

Order Service FastAPI application entry point.

Lifespan (startup/shutdown):
  1. Configure structured logging
  2. Configure OpenTelemetry tracing
  3. Initialize DB session factory
  4. Create tables (local dev only — use Alembic in production)
  5. Start Kafka producer
  6. Start outbox relay as background task
  7. Start Kafka consumer as background task
  8. Graceful shutdown on exit
"""

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import health, orders
from app.consumers.order_consumer import OrderEventConsumer
from app.core.config import get_settings
from app.db.session import create_tables, init_order_db
from app.producers.order_events import OutboxRelay
from libs.common.kafka.producer import KafkaProducer
from libs.common.logging import configure_logging, get_logger
from libs.common.tracing import configure_tracing

logger = get_logger(__name__)

# ── Module-level references so shutdown can access them ───────────────────────
_producer: KafkaProducer | None = None
_consumer: OrderEventConsumer | None = None
_relay: OutboxRelay | None = None
_background_tasks: list[asyncio.Task] = []


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown lifecycle for the Order Service."""
    global _producer, _consumer, _relay, _background_tasks

    settings = get_settings()

    # ── 1. Logging ────────────────────────────────────────────────────────────
    configure_logging(settings.service_name, settings.log_level)
    logger.info("Starting Order Service", environment=settings.environment)

    # ── 2. Tracing ────────────────────────────────────────────────────────────
    if settings.otel_traces_enabled:
        configure_tracing(settings.service_name, settings.otel_exporter_otlp_endpoint)
        logger.info("OpenTelemetry tracing configured")

    # ── 3. Database ───────────────────────────────────────────────────────────
    init_order_db()
    logger.info("Database session factory initialized")

    # ── 4. Create tables (local dev only) ─────────────────────────────────────
    if settings.environment == "local":
        await create_tables()
        logger.info("Tables created (local dev mode)")

    # ── 5. Kafka producer ─────────────────────────────────────────────────────
    _producer = KafkaProducer(settings.kafka_bootstrap_servers)
    await _producer.start()

    # ── 6. Outbox relay ───────────────────────────────────────────────────────
    _relay = OutboxRelay(_producer)
    relay_task = asyncio.create_task(_relay.start(), name="outbox-relay")
    _background_tasks.append(relay_task)

    # ── 7. Kafka consumer ─────────────────────────────────────────────────────
    _consumer = OrderEventConsumer(
        topics=settings.topics_consume,
        group_id=settings.kafka_consumer_group_id,
        bootstrap_servers=settings.kafka_bootstrap_servers,
        dlq_producer=_producer,
    )
    consumer_task = asyncio.create_task(_consumer.start(), name="kafka-consumer")
    _background_tasks.append(consumer_task)

    logger.info(
        "Order Service started",
        topics_consuming=settings.topics_consume,
    )

    yield   # ── Application runs ───────────────────────────────────────────────

    # ── Shutdown ──────────────────────────────────────────────────────────────
    logger.info("Shutting down Order Service")

    if _relay:
        await _relay.stop()
    if _consumer:
        await _consumer.stop()
    if _producer:
        await _producer.stop()

    for task in _background_tasks:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    logger.info("Order Service stopped cleanly")


# ── FastAPI app ───────────────────────────────────────────────────────────────

app = FastAPI(
    title="Order Service",
    description="Core order orchestration service for the Event-Driven Delivery Platform",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# ── Middleware ────────────────────────────────────────────────────────────────

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],    # tighten in production
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Log every inbound request with method, path, and response status."""
    response = await call_next(request)
    logger.info(
        "HTTP request",
        method=request.method,
        path=request.url.path,
        status_code=response.status_code,
    )
    return response


# ── Exception handlers ────────────────────────────────────────────────────────

@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.error(
        "Unhandled exception",
        method=request.method,
        path=request.url.path,
        error=str(exc),
        exc_info=True,
    )
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "Internal server error"},
    )


# ── Routers ───────────────────────────────────────────────────────────────────

app.include_router(health.router)
app.include_router(orders.router, prefix="/v1")
