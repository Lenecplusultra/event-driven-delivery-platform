#!/usr/bin/env bash
# scripts/bootstrap-topics.sh
#
# Creates all Kafka topics defined in SPEC.md §8.
# Run once after `docker compose up` before starting any service.
#
# Usage:
#   ./scripts/bootstrap-topics.sh
#   KAFKA_BOOTSTRAP=kafka:9092 ./scripts/bootstrap-topics.sh

set -euo pipefail

KAFKA_BOOTSTRAP="${KAFKA_BOOTSTRAP:-localhost:9092}"
PARTITIONS=3
REPLICATION=1

echo "Bootstrap server: $KAFKA_BOOTSTRAP"
echo "Creating Kafka topics..."

create_topic() {
  local topic="$1"
  local partitions="${2:-$PARTITIONS}"
  echo "  Creating: $topic (partitions=$partitions)"
  docker exec kafka kafka-topics \
    --bootstrap-server "$KAFKA_BOOTSTRAP" \
    --create \
    --if-not-exists \
    --topic "$topic" \
    --partitions "$partitions" \
    --replication-factor "$REPLICATION"
}

# ── Core topics ───────────────────────────────────────────────────────────────
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

# ── Retry topics ──────────────────────────────────────────────────────────────
create_topic "payment.requested.retry"
create_topic "dispatch.requested.retry"
create_topic "notification.requested.retry"

# ── Dead-letter topics ────────────────────────────────────────────────────────
create_topic "payment.requested.dlq"        1
create_topic "dispatch.requested.dlq"       1
create_topic "notification.requested.dlq"   1

echo ""
echo "All topics created. Listing:"
docker exec kafka kafka-topics \
  --bootstrap-server "$KAFKA_BOOTSTRAP" \
  --list

echo ""
echo "Done."
