"""
services/dispatch-service/app/main.py

Dispatch Service entry point.

Lifespan:
  1. Logging + tracing
  2. DB init + table creation (local)
  3. Redis connection
  4. Kafka producer start
  5. Seed simulated drivers (local dev)
  6. Kafka consumer start (dispatch.requested)
  7. Graceful shutdown
"""

import asyncio
from contextlib import asynccontextmanager

import redis.asyncio as aioredis
from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import dispatches, health
from app.cache.driver_cache import DriverCache
from app.consumers.dispatch_consumer import DispatchEventConsumer
from app.core.config import get_settings
from app.core.dependencies import set_redis_client
from app.db.session import create_tables, init_dispatch_db
from libs.common.kafka.producer import KafkaProducer
from libs.common.logging import configure_logging, get_logger
from libs.common.tracing import configure_tracing

logger = get_logger(__name__)

_producer: KafkaProducer | None = None
_consumer: DispatchEventConsumer | None = None
_background_tasks: list[asyncio.Task] = []


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _producer, _consumer, _background_tasks

    settings = get_settings()

    configure_logging(settings.service_name, settings.log_level)
    logger.info("Starting Dispatch Service", environment=settings.environment)

    if settings.otel_traces_enabled:
        try:
            configure_tracing(settings.service_name, settings.otel_exporter_otlp_endpoint)
            logger.info("OpenTelemetry tracing configured")
        except Exception as exc:
            logger.warning("OTel tracing setup failed (non-fatal)", error=str(exc))

    init_dispatch_db()

    if settings.environment == "local":
        await create_tables()
        logger.info("Tables created (local dev)")

    # ── Redis ─────────────────────────────────────────────────────────────────
    redis_client = aioredis.from_url(
        settings.redis_url, encoding="utf-8", decode_responses=False
    )
    set_redis_client(redis_client)
    logger.info("Redis connected")

    # ── Kafka producer ────────────────────────────────────────────────────────
    _producer = KafkaProducer(settings.kafka_bootstrap_servers)
    await _producer.start()

    # ── Seed simulated drivers (local dev) ────────────────────────────────────
    if settings.environment == "local":
        from libs.common.db.session import get_session_factory
        from app.services.dispatch_service import DispatchService
        cache = DriverCache(redis_client)
        async with get_session_factory()() as session:
            async with session.begin():
                svc = DispatchService(session, cache)
                await svc.seed_drivers(settings.simulated_driver_count)
        logger.info("Drivers seeded", count=settings.simulated_driver_count)

    # ── Kafka consumer ────────────────────────────────────────────────────────
    _consumer = DispatchEventConsumer(
        producer=_producer,
        redis_client=redis_client,
        topics=settings.topics_consume,
        group_id=settings.kafka_consumer_group_id,
        bootstrap_servers=settings.kafka_bootstrap_servers,
        dlq_producer=_producer,
    )
    consumer_task = asyncio.create_task(_consumer.start(), name="kafka-consumer")
    _background_tasks.append(consumer_task)

    logger.info("Dispatch Service started", topics=settings.topics_consume)

    yield

    logger.info("Shutting down Dispatch Service")
    if _consumer:
        await _consumer.stop()
    if _producer:
        await _producer.stop()
    await redis_client.aclose()

    for task in _background_tasks:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    logger.info("Dispatch Service stopped cleanly")


app = FastAPI(
    title="Dispatch Service",
    description="Driver assignment and delivery progression for the delivery platform",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.middleware("http")
async def log_requests(request: Request, call_next):
    response = await call_next(request)
    logger.info(
        "HTTP request",
        method=request.method,
        path=request.url.path,
        status_code=response.status_code,
    )
    return response


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.error("Unhandled exception", path=request.url.path, error=str(exc), exc_info=True)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "Internal server error"},
    )


app.include_router(health.router)
app.include_router(dispatches.router, prefix="/v1")
