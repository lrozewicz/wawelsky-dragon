#!/usr/bin/env bash
# Zatrzymuje testowy Keycloak i usuwa kontener, sieć oraz wolumeny (kontrakt WP E0-3 C11).
# Działa z dowolnego bieżącego katalogu.
set -euo pipefail

DIR="$(dirname "$(readlink -f "$0")")"

docker compose -f "$DIR/docker-compose.keycloak.yml" down -v --remove-orphans
