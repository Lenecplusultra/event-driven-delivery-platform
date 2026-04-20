# Event-Driven Order Fulfillment Platform

A production-shaped distributed backend that demonstrates real microservice domain boundaries,
high-throughput async event streaming, Saga orchestration with compensating transactions,
Redis caching, Kubernetes horizontal autoscaling, and full distributed tracing via OpenTelemetry.

## Stack

| Layer | Technology |
|---|---|
| Language | Python 3.12 |
| Web framework | FastAPI |
| Async event bus | Apache Kafka |
| Cache / ephemeral state | Redis |
| Persistence | PostgreSQL 16 (one DB per service) |
| Containerization | Docker + Docker Compose |
| Orchestration | Kubernetes + KEDA |
| Observability | OpenTelemetry → Prometheus / Grafana / Jaeger |

## Architecture

```
Client → API Gateway → FastAPI services → PostgreSQL (per service)
                                         → Kafka (async events)
                                         → Redis (cache / ephemeral)
All services → OpenTelemetry Collector → Prometheus / Grafana / Jaeger
```

See [`SPEC.md`](./SPEC.md) for the full Phase 1 specification, event contracts,
Kafka topic design, Saga flow, DLQ strategy, and Kubernetes HPA configuration.

## Services

| Service | Responsibility |
|---|---|
| `api-gateway` | Single public entry point, routing, rate limiting |
| `auth-service` | JWT issuance, roles, user auth |
| `customer-service` | Customer profiles and addresses |
| `restaurant-service` | Restaurant catalog, menus, availability |
| `order-service` | Core order orchestration and state machine |
| `payment-service` | Simulated payment authorization with idempotency |
| `dispatch-service` | Driver assignment and delivery progression |
| `notification-service` | Email/SMS/in-app notifications via events |

## Order Lifecycle

```
CREATED → PENDING_RESTAURANT_CONFIRMATION → RESTAURANT_CONFIRMED
       → PAYMENT_PENDING → PAYMENT_AUTHORIZED → PREPARING
       → READY_FOR_PICKUP → DRIVER_ASSIGNED → OUT_FOR_DELIVERY → DELIVERED
```

Failure states: `RESTAURANT_REJECTED`, `PAYMENT_FAILED`, `CANCELLED`,
`DELIVERY_FAILED`, `REFUNDED`

## Quick Start (local)

```bash
# 1. Clone and enter repo
git clone <repo-url>
cd event-driven-delivery-platform

# 2. Copy root env
cp .env.example .env

# 3. Start infra (Kafka, Postgres, Redis, OTEL Collector)
docker compose -f infra/docker/docker-compose.yml up -d

# 4. Bootstrap Kafka topics
./scripts/bootstrap-topics.sh

# 5. Start Order Service
cd services/order-service
cp .env.example .env
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8001

# 6. Test
curl -X POST http://localhost:8001/orders \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: $(uuidgen)" \
  -d @scripts/sample_order.json
```

## Repo Structure

```
event-driven-delivery-platform/
├── docs/           Architecture docs and ADRs
├── infra/          Docker Compose, Kubernetes manifests, observability config
├── libs/           Shared Python libraries (common, contracts)
├── services/       Individual microservices
└── scripts/        Bootstrap and seed scripts
```

## Observability

- Distributed traces: Jaeger at `http://localhost:16686`
- Metrics: Prometheus at `http://localhost:9090`
- Dashboards: Grafana at `http://localhost:3000`

## Phase 1 Progress

- [x] Architecture spec locked
- [x] Repository skeleton
- [ ] Local infra (Docker Compose)
- [ ] Order Service v1
- [ ] Restaurant Service
- [ ] Payment Service
- [ ] Dispatch Service
- [ ] Notification Service
- [ ] Redis caching layer
- [ ] Full OpenTelemetry instrumentation
- [ ] Kubernetes manifests + HPA + KEDA
- [ ] Grafana dashboards + alerting
