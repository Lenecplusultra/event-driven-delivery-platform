"""
services/payment-service/app/main.py

Payment Service entry point.
"""

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import health, payments
from app.consumers.payment_consumer import PaymentEventConsumer
from app.core.config import get_settings
from app.db.session import create_tables, init_payment_db
from libs.common.kafka.producer import KafkaProducer
from libs.common.logging import configure_logging, get_logger
from libs.common.tracing import configure_tracing

logger = get_logger(__name__)

_producer: KafkaProducer | None = None
_consumer: PaymentEventConsumer | None = None
_background_tasks: list[asyncio.Task] = []


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _producer, _consumer, _background_tasks
    settings = get_settings()

    configure_logging(settings.service_name, settings.log_level)
    logger.info("Starting Payment Service", environment=settings.environment)

    if settings.otel_traces_enabled:
        try:
            configure_tracing(settings.service_name, settings.otel_exporter_otlp_endpoint)
            logger.info("OpenTelemetry tracing configured")
        except Exception as exc:
            # OTel collector may not be ready yet — non-fatal, service continues
            logger.warning("OTel tracing setup failed (non-fatal)", error=str(exc))

    init_payment_db()

    if settings.environment == "local":
        await create_tables()
        logger.info("Tables created (local dev)")

    _producer = KafkaProducer(settings.kafka_bootstrap_servers)
    await _producer.start()

    _consumer = PaymentEventConsumer(
        producer=_producer,
        topics=settings.topics_consume,
        group_id=settings.kafka_consumer_group_id,
        bootstrap_servers=settings.kafka_bootstrap_servers,
        dlq_producer=_producer,
    )
    consumer_task = asyncio.create_task(_consumer.start(), name="kafka-consumer")
    _background_tasks.append(consumer_task)

    logger.info(
        "Payment Service started",
        failure_rate=settings.simulated_failure_rate,
        topics=settings.topics_consume,
    )

    yield

    logger.info("Shutting down Payment Service")
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
    logger.info("Payment Service stopped cleanly")


app = FastAPI(
    title="Payment Service",
    description="Idempotent payment authorization with simulated gateway for the delivery platform",
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
app.include_router(payments.router, prefix="/v1")
