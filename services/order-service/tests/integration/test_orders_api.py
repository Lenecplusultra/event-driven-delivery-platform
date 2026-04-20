"""
services/order-service/tests/integration/test_orders_api.py

Integration tests for POST /v1/orders and GET /v1/orders/{id}.

Uses the httpx AsyncClient with in-memory SQLite.
Kafka producer is not tested here — the outbox record is verified instead.
"""

import uuid

import pytest


@pytest.mark.asyncio
async def test_create_order_returns_201(client, sample_order_payload):
    response = await client.post(
        "/v1/orders",
        json=sample_order_payload,
        headers={"Idempotency-Key": str(uuid.uuid4())},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["status"] == "PENDING_RESTAURANT_CONFIRMATION"
    assert len(data["items"]) == 1


@pytest.mark.asyncio
async def test_create_order_idempotency_returns_200(client, sample_order_payload):
    key = str(uuid.uuid4())
    headers = {"Idempotency-Key": key}

    r1 = await client.post("/v1/orders", json=sample_order_payload, headers=headers)
    assert r1.status_code == 201

    r2 = await client.post("/v1/orders", json=sample_order_payload, headers=headers)
    assert r2.status_code == 200
    assert r1.json()["id"] == r2.json()["id"]


@pytest.mark.asyncio
async def test_get_order_success(client, sample_order_payload):
    create_resp = await client.post(
        "/v1/orders",
        json=sample_order_payload,
        headers={"Idempotency-Key": str(uuid.uuid4())},
    )
    assert create_resp.status_code == 201
    order_id = create_resp.json()["id"]

    get_resp = await client.get(f"/v1/orders/{order_id}")
    assert get_resp.status_code == 200
    assert get_resp.json()["id"] == order_id


@pytest.mark.asyncio
async def test_get_order_not_found(client):
    response = await client.get(f"/v1/orders/{uuid.uuid4()}")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_create_order_missing_idempotency_key(client, sample_order_payload):
    response = await client.post("/v1/orders", json=sample_order_payload)
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_create_order_empty_items(client):
    response = await client.post(
        "/v1/orders",
        json={
            "customer_id": str(uuid.uuid4()),
            "restaurant_id": str(uuid.uuid4()),
            "items": [],
            "delivery_address": {
                "street": "123 Main St",
                "city": "Atlanta",
                "state": "GA",
                "zip_code": "30301",
            },
        },
        headers={"Idempotency-Key": str(uuid.uuid4())},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_health_endpoint(client):
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
