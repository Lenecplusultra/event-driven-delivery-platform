"""
services/payment-service/app/services/gateway_simulator.py

Simulated payment gateway.

Replaces a real payment provider (Stripe, Adyen, etc.) for local dev and demos.

Behavior:
  - Introduces configurable processing delay
  - Fails at a configurable rate (default 10%)
  - Generates a fake gateway reference ID
  - Always fails if amount exceeds hard ceiling
  - Can be forced to fail or succeed via special idempotency key prefixes
    (useful for writing deterministic tests without mocking)

Special idempotency key prefixes (test overrides):
  "test-fail-"    → always FAILED
  "test-ok-"      → always AUTHORIZED
  "test-timeout-" → raises TimeoutError (tests DLQ path)
"""

import asyncio
import random
import time
import uuid
from dataclasses import dataclass
from enum import Enum


class GatewayResult(str, Enum):
    AUTHORIZED = "AUTHORIZED"
    DECLINED = "DECLINED"
    TIMEOUT = "TIMEOUT"


@dataclass
class GatewayResponse:
    result: GatewayResult
    gateway_reference: str | None
    failure_reason: str | None
    processing_duration_ms: int


class PaymentGatewaySimulator:
    def __init__(
        self,
        failure_rate: float = 0.1,
        processing_delay_seconds: float = 0.3,
        max_amount_cents: int = 100_000,
    ) -> None:
        self._failure_rate = failure_rate
        self._processing_delay = processing_delay_seconds
        self._max_amount_cents = max_amount_cents

    async def authorize(
        self,
        amount_cents: int,
        idempotency_key: str,
    ) -> GatewayResponse:
        """
        Simulate a payment authorization call to an external gateway.

        Returns a GatewayResponse with result AUTHORIZED or DECLINED.
        Raises asyncio.TimeoutError for the test-timeout- prefix.
        """
        start = time.monotonic()
        await asyncio.sleep(self._processing_delay)
        elapsed_ms = int((time.monotonic() - start) * 1000)

        # ── Test overrides via idempotency key prefix ──────────────────────────
        if idempotency_key.startswith("test-timeout-"):
            raise asyncio.TimeoutError("Simulated gateway timeout")

        if idempotency_key.startswith("test-fail-"):
            return GatewayResponse(
                result=GatewayResult.DECLINED,
                gateway_reference=None,
                failure_reason="Simulated forced failure",
                processing_duration_ms=elapsed_ms,
            )

        if idempotency_key.startswith("test-ok-"):
            return GatewayResponse(
                result=GatewayResult.AUTHORIZED,
                gateway_reference=f"gw-{uuid.uuid4().hex[:12]}",
                failure_reason=None,
                processing_duration_ms=elapsed_ms,
            )

        # ── Hard ceiling check ────────────────────────────────────────────────
        if amount_cents > self._max_amount_cents:
            return GatewayResponse(
                result=GatewayResult.DECLINED,
                gateway_reference=None,
                failure_reason=(
                    f"Amount {amount_cents} cents exceeds maximum "
                    f"{self._max_amount_cents} cents"
                ),
                processing_duration_ms=elapsed_ms,
            )

        # ── Probabilistic failure ─────────────────────────────────────────────
        if random.random() < self._failure_rate:
            reasons = [
                "Insufficient funds",
                "Card declined by issuer",
                "Fraud risk score too high",
                "Card expired",
            ]
            return GatewayResponse(
                result=GatewayResult.DECLINED,
                gateway_reference=None,
                failure_reason=random.choice(reasons),
                processing_duration_ms=elapsed_ms,
            )

        # ── Success ───────────────────────────────────────────────────────────
        return GatewayResponse(
            result=GatewayResult.AUTHORIZED,
            gateway_reference=f"gw-{uuid.uuid4().hex[:12]}",
            failure_reason=None,
            processing_duration_ms=elapsed_ms,
        )

    async def refund(
        self,
        gateway_reference: str,
        amount_cents: int,
    ) -> GatewayResponse:
        """Simulate a refund call. Always succeeds in simulation."""
        await asyncio.sleep(self._processing_delay * 0.5)
        return GatewayResponse(
            result=GatewayResult.AUTHORIZED,
            gateway_reference=f"ref-{uuid.uuid4().hex[:12]}",
            failure_reason=None,
            processing_duration_ms=int(self._processing_delay * 500),
        )
