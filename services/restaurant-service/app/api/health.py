"""
services/restaurant-service/app/api/health.py
"""

from fastapi import APIRouter, status
from fastapi.responses import JSONResponse
from sqlalchemy import text

from libs.common.logging import get_logger

router = APIRouter(tags=["health"])
logger = get_logger(__name__)


def _get_db_factory():
    from libs.common.db.session import get_session_factory
    return get_session_factory()


def _get_redis():
    from app.core.dependencies import get_redis_client
    return get_redis_client()


@router.get("/health", status_code=status.HTTP_200_OK)
async def liveness():
    return {"status": "ok"}


@router.get("/ready", status_code=status.HTTP_200_OK)
async def readiness():
    checks: dict[str, str] = {}

    try:
        factory = _get_db_factory()
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

    try:
        redis = _get_redis()
        await redis.ping()
        checks["redis"] = "ok"
    except Exception as exc:
        logger.error("Readiness check failed: redis", error=str(exc))
        checks["redis"] = f"error: {exc}"
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"status": "not_ready", "checks": checks},
        )

    return {"status": "ready", "checks": checks}
