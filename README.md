# Event-Driven Order Fulfillment Platform

A production-shaped distributed backend demonstrating real microservice domain boundaries,
high-throughput async event streaming, Saga orchestration with compensating transactions,
Redis caching, Kubernetes horizontal autoscaling, and full distributed tracing via OpenTelemetry.

## Stack

| Layer | Technology |
|---|---|
| Language | Python 3.12 |
| Web framework | FastAPI |
| Async event bus | Apache Kafka (KRaft) |
| Cache / ephemeral state | Redis |
| Persistence | PostgreSQL 16 (one DB per service) |
| Containerization | Docker + Docker Compose |
| Orchestration | Kubernetes + KEDA |
| Observability | OpenTelemetry → Prometheus / Grafana / Jaeger |

## Quick Start

Everything runs inside Docker — no local Python needed to try it.

```bash
# 1. Clone
git clone https://github.com/YOUR_USERNAME/event-driven-delivery-platform.git
cd event-driven-delivery-platform

# 2. Build and start the full stack
docker compose -f infra/docker/docker-compose.yml up --build

# 3. Create Kafka topics (new terminal, while stack is running)
./scripts/bootstrap-topics.sh

# 4. Place a test order
curl -X POST http://localhost:8001/v1/orders \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: $(uuidgen)" \
  -d '{
    "customer_id": "11111111-1111-1111-1111-111111111111",
    "restaurant_id": "22222222-2222-2222-2222-222222222222",
    "items": [{"item_id": "33333333-3333-3333-3333-333333333333",
               "name": "Margherita", "quantity": 1, "unit_price": "14.99"}],
    "delivery_address": {"street": "123 Main St", "city": "Atlanta",
                          "state": "GA", "zip_code": "30301"}
  }'

# 5. Watch the order state advance through the Saga
curl http://localhost:8001/v1/orders/{order_id}/history
```

## Services

| Service | Port | Responsibility |
|---|---|---|
| `order-service` | 8001 | Core order orchestration and state machine |
| `restaurant-service` | 8002 | Restaurant catalog, menus, order confirmation |
| `payment-service` | 8003 | Idempotent payment authorization |
| `dispatch-service` | 8004 | Driver assignment and delivery *(coming soon)* |
| `notification-service` | 8005 | Email/SMS/in-app notifications *(coming soon)* |

## Order Lifecycle (Saga)

```
POST /orders
  → order.created
    → restaurant.order_confirmed
      → payment.requested
        → payment.authorized
          → order.preparing
            → order.ready_for_pickup
              → dispatch.requested
                → driver.assigned
                  → delivery.picked_up
                    → delivery.completed → DELIVERED ✓

Failure paths:
  restaurant.order_rejected     → RESTAURANT_REJECTED
  payment.failed                → PAYMENT_FAILED → CANCELLED
  delivery.failed               → DELIVERY_FAILED → REFUNDED
```

## Observability

| Tool | URL | What you see |
|---|---|---|
| Jaeger | http://localhost:16686 | Distributed traces — full request flow across services |
| Prometheus | http://localhost:9090 | Raw metrics — latency, error rates, Kafka lag |
| Grafana | http://localhost:3000 (admin/admin) | Dashboards |

## Architecture Principles

- **Database per service** — no cross-service DB queries, ever
- **Outbox pattern** — state change + event write in one DB transaction, relay publishes to Kafka
- **Saga orchestration** — Order Service drives the workflow; compensating transactions on failure
- **Idempotent consumers** — every event handler is safe to replay
- **Correlation ID everywhere** — trace any order across all services and events
- **Redis caching** — menu data and driver availability cached to reduce DB pressure

## Repo Structure

```
event-driven-delivery-platform/
├── docs/           Architecture docs and ADRs
├── infra/          Docker Compose, Kubernetes manifests, observability config
├── libs/           Shared Python libraries (common tooling + event contracts)
├── services/       Microservices (one folder per service)
└── scripts/        Bootstrap and seed scripts
```

## Running Tests

```bash
# From any service directory
cd services/order-service
pip install -r requirements.txt
pytest tests/ -v
```

## Inspecting a database

Postgres instances have no host ports (correct design — services talk internally).
Use docker exec to connect:

```bash
docker exec -it order-db psql -U delivery -d order_db
```
