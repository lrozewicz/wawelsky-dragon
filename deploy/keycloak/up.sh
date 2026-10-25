#!/usr/bin/env bash
# Startuje testowy Keycloak (kontrakt WP E0-3 C11). Idempotentny: gdy usługa keycloak
# projektu wd-keycloak jest running i healthy — komunikat i kod 0, bez `compose up`.
# Działa z dowolnego bieżącego katalogu; port hosta z KC_PORT (dom. 8180).
set -euo pipefail

DIR="$(dirname "$(readlink -f "$0")")"
COMPOSE_FILE="$DIR/docker-compose.keycloak.yml"
PORT="${KC_PORT:-8180}"

health="$(docker compose -f "$COMPOSE_FILE" ps --format '{{.Health}}' keycloak 2>/dev/null || true)"
if [ "$health" = "healthy" ]; then
  echo "Keycloak testowy już działa (port $PORT)"
  exit 0
fi

docker compose -f "$COMPOSE_FILE" up -d --build --wait
echo "Keycloak testowy gotowy: http://localhost:${KC_PORT:-8180}/realms/wawelsky-test"
