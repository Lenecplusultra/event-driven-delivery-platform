#!/usr/bin/env bash
# scripts/bootstrap-topics.sh
#
# Creates all Kafka topics. Runs inside the kafka container via docker exec.
# Must be run AFTER `docker compose up` has started the kafka container.
#
# Usage (from repo root):
#   ./scripts/bootstrap-topics.sh

set -euo pipefail

KAFKA_CONTAINER="${KAFKA_CONTAINER:-kafka}"
BOOTSTRAP="localhost:9092"   # inside the container, localhost = kafka itself
PARTITIONS=3
REPLICATION=1

# Verify kafka container is running
if ! docker ps --format '{{.Names}}' | grep -q "^${KAFKA_CONTAINER}$"; then
  echo "Error: container '${KAFKA_CONTAINER}' is not running."
  echo "Run: docker compose -f infra/docker/docker-compose.yml up -d kafka"
  exit 1
fi

echo "Creating Kafka topics inside container '${KAFKA_CONTAINER}'..."

create_topic() {
  local topic="$1"
  local partitions="${2:-$PARTITIONS}"
  echo "  → $topic (partitions=$partitions)"
  docker exec "$KAFKA_CONTAINER" kafka-topics \
    --bootstrap-server "$BOOTSTRAP" \
    --create \
    --if-not-exists \
    --topic "$topic" \
    --partitions "$partitions" \
    --replication-factor "$REPLICATION"
}

# ── Core topics ────────────────────────────────────────────────────────────
create_topic "order.created"
create_topic "restaurant.order_confirmed"
create_topic "restaurant.order_rejected"
create_topic "payment.requested"
create_topic "payment.authorized"
create_topic "payment.failed"
create_topic "order.preparing"
create_topic "order.ready_for_pickup"
create_topic "dispatch.requested"
create_topic "driver.assigned"
create_topic "delivery.picked_up"
create_topic "delivery.completed"
create_topic "delivery.failed"
create_topic "notification.requested"

# ── Retry topics ───────────────────────────────────────────────────────────
create_topic "payment.requested.retry"
create_topic "dispatch.requested.retry"
create_topic "notification.requested.retry"

# ── Dead-letter topics (single partition — order doesn't matter here) ──────
create_topic "payment.requested.dlq"      1
create_topic "dispatch.requested.dlq"     1
create_topic "notification.requested.dlq" 1

echo ""
echo "All topics created. Full list:"
docker exec "$KAFKA_CONTAINER" kafka-topics \
  --bootstrap-server "$BOOTSTRAP" \
  --list
echo ""
echo "Done."
