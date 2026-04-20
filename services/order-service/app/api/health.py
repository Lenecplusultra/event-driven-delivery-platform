"""
services/order-service/app/api/health.py

Liveness and readiness probes consumed by Kubernetes.

GET /health  — liveness:  is the process alive?
GET /ready   — readiness: are DB and Kafka connections healthy?

Kubernetes will:
  - restart the pod if /health fails repeatedly
  - stop routing traffic to the pod if /ready fails
"""

from fastapi import APIRouter, status
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.core.dependencies import get_db_factory
from libs.common.logging import get_logger

router = APIRouter(tags=["health"])
logger = get_logger(__name__)


@router.get("/health", status_code=status.HTTP_200_OK)
async def liveness():
    """Liveness probe — always 200 if the process is running."""
    return {"status": "ok"}


@router.get("/ready", status_code=status.HTTP_200_OK)
async def readiness():
    """
    Readiness probe — checks DB connectivity.
    Returns 503 if the database is unreachable.
    """
    checks: dict[str, str] = {}

    # ── DB check ──────────────────────────────────────────────────────────────
    try:
        factory = get_db_factory()
        async with factory() as session:
            await session.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as exc:
        logger.error("Readiness check failed: database", error=str(exc))
        checks["database"] = f"error: {exc}"
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"status": "not_ready", "checks": checks},
        )

    return {"status": "ready", "checks": checks}
