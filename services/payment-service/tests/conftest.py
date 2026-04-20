"""
services/payment-service/tests/conftest.py
"""

import uuid
import pytest


@pytest.fixture
def sample_order_id():
    return uuid.uuid4()


@pytest.fixture
def ok_idempotency_key():
    """Always produces an AUTHORIZED result from the simulator."""
    return f"test-ok-{uuid.uuid4()}"


@pytest.fixture
def fail_idempotency_key():
    """Always produces a DECLINED result from the simulator."""
    return f"test-fail-{uuid.uuid4()}"
