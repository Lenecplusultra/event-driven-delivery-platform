"""
services/payment-service/app/api/health.py
"""

from fastapi import APIRouter, status
from fastapi.responses import JSONResponse
from sqlalchemy import text
from libs.common.db.session import get_session_factory
from libs.common.logging import get_logger

router = APIRouter(tags=["health"])
logger = get_logger(__name__)


@router.get("/health", status_code=status.HTTP_200_OK)
async def liveness():
    return {"status": "ok"}


@router.get("/ready", status_code=status.HTTP_200_OK)
async def readiness():
    checks: dict[str, str] = {}
    try:
        factory = get_session_factory()
        async with factory() as session:
            await session.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as exc:
        checks["database"] = f"error: {exc}"
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"status": "not_ready", "checks": checks},
        )
    return {"status": "ready", "checks": checks}
