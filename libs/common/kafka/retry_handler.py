"""
libs/common/kafka/retry_handler.py

Exponential backoff retry handler for Kafka consumers.

Backoff schedule (matches SPEC.md §9):
  Attempt 1: 1s
  Attempt 2: 4s
  Attempt 3: 16s
  After 3 failures: route to DLQ
"""

import asyncio


BACKOFF_SECONDS: list[float] = [1.0, 4.0, 16.0]


async def with_backoff(attempt: int) -> None:
    """
    Await the configured backoff delay for the given retry attempt.

    Args:
        attempt: 1-indexed attempt number. Attempt 1 uses the first delay.
    """
    idx = min(attempt - 1, len(BACKOFF_SECONDS) - 1)
    delay = BACKOFF_SECONDS[idx]
    await asyncio.sleep(delay)
