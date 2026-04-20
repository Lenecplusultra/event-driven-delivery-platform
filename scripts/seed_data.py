#!/usr/bin/env python3
"""
scripts/seed_data.py

Seeds local development databases with test data.

Usage:
    python scripts/seed_data.py

Requires services to be running with tables already created.
"""

import asyncio
import uuid

import httpx

ORDER_SERVICE_URL = "http://localhost:8001"


SAMPLE_ORDER = {
    "customer_id": str(uuid.uuid4()),
    "restaurant_id": str(uuid.uuid4()),
    "items": [
        {
            "item_id": str(uuid.uuid4()),
            "name": "Margherita Pizza",
            "quantity": 1,
            "unit_price": "14.99",
        },
        {
            "item_id": str(uuid.uuid4()),
            "name": "Caesar Salad",
            "quantity": 2,
            "unit_price": "8.50",
        },
    ],
    "delivery_address": {
        "street": "456 Peachtree St NW",
        "city": "Atlanta",
        "state": "GA",
        "zip_code": "30308",
        "country": "US",
    },
}


async def seed_orders(n: int = 3) -> None:
    async with httpx.AsyncClient() as client:
        for i in range(n):
            key = str(uuid.uuid4())
            resp = await client.post(
                f"{ORDER_SERVICE_URL}/v1/orders",
                json=SAMPLE_ORDER,
                headers={"Idempotency-Key": key},
            )
            if resp.status_code in (200, 201):
                data = resp.json()
                print(f"  Order {i+1}: {data['id']} — {data['status']}")
            else:
                print(f"  Order {i+1}: FAILED — {resp.status_code} {resp.text}")


async def main() -> None:
    print("Seeding Order Service...")
    await seed_orders(n=3)
    print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
