#!/usr/bin/env bash
# Pomiar SC-E6-1a-06: filtr metadata_condition na 10 000 dokumentów (WP E6-1a, T6).
# Startuje izolowany stos testowy, zasiewa 10k dokumentów z meta_fields (bez parsowania)
# i mierzy po HTTP GET /api/v1/datasets/{id}/documents?metadata_condition=… (3 rozgrzewki
# + 20 prób), po czym ZDEJMUJE stos. Wynik JSON: tools/perf/out/meta-filter-10k.json.
#
#   tools/perf/meta-filter-10k.sh [--documents N] [--samples N] [--warmup N] [--budget-ms MS]
#
# rc != 0, gdy p95 > --budget-ms (dom. 200). Parametry biegu przekazywane wprost do
# wdperf.meta_filter (uruchamiany z backend/ z PYTHONPATH na pakiet wdperf).
set -euo pipefail
ROOT="$(git rev-parse --show-toplevel)"; cd "$ROOT"

eval "$(tools/dev/up.sh test env)"
API="http://${WD_HOST:-host.docker.internal}:$WD_TEST_API_PORT"
OUT_DIR="$ROOT/tools/perf/out"; mkdir -p "$OUT_DIR"

cleanup() { "$ROOT/tools/dev/up.sh" test down >&2 || true; }
trap cleanup EXIT INT TERM

tools/dev/up.sh test up mariadb-test migrate api >&2

rc=0
cd "$ROOT/backend"
env PYTHONPATH="../tools/perf:." uv run --frozen python -m wdperf.meta_filter \
  --api "$API" --db-host "$WD_DB_HOST" --db-port "$WD_DB_PORT" \
  --out "$OUT_DIR/meta-filter-10k.json" "$@" || rc=$?
exit "$rc"
