#!/usr/bin/env bash
# backup.sh — kopia B1: dump bazy MariaDB, tar wolumenu danych i manifest sha256 (kontrakt WP E5-3 C3).
#
# Użycie:
#   scripts/backup.sh --out DIR [--compose-file FILE] [--project NAME] [--db-service SVC]
#                     [--data-volume VOL] [--retain-days N] [--prune-only]
#
# Domyślnie: --compose-file docker-compose.yml (względem korzenia repo), --db-service mariadb,
# --data-volume app-data, --retain-days 14 (0 = bez retencji). --out jest obowiązkowe.
# --prune-only wykonuje wyłącznie retencję w --out (bez Dockera) i kończy kodem 0.
# Hasło root MariaDB jest czytane wyłącznie wewnątrz kontenera (ze środowiska kontenera).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

usage() {
  echo "użycie: backup.sh --out DIR [--compose-file FILE] [--project NAME] [--db-service SVC]" >&2
  echo "                    [--data-volume VOL] [--retain-days N] [--prune-only]" >&2
}

OUT=""
COMPOSE_FILE="$ROOT/docker-compose.yml"
PROJECT=""
DB_SERVICE="mariadb"
DATA_VOLUME="app-data"
RETAIN_DAYS=14
PRUNE_ONLY=false

while [ $# -gt 0 ]; do
  case "$1" in
    --prune-only)
      PRUNE_ONLY=true
      shift
      ;;
    --out|--compose-file|--project|--db-service|--data-volume|--retain-days)
      [ $# -ge 2 ] || { usage; exit 2; }
      case "$1" in
        --out) OUT="$2" ;;
        --compose-file) COMPOSE_FILE="$2" ;;
        --project) PROJECT="$2" ;;
        --db-service) DB_SERVICE="$2" ;;
        --data-volume) DATA_VOLUME="$2" ;;
        --retain-days) RETAIN_DAYS="$2" ;;
      esac
      shift 2
      ;;
    *)
      usage
      exit 2
      ;;
  esac
done

[ -n "$OUT" ] || { usage; exit 2; }
case "$RETAIN_DAYS" in
  ''|*[!0-9]*) echo "backup.sh: --retain-days musi być liczbą" >&2; exit 2 ;;
esac

# Retencja: usuwa wyłącznie pliki kopii (db-*.sql.zst, data-*.tar.zst, manifest-*.json)
# starsze niż N dni; nigdy plików bieżącej ani cudzych.
prune_old() {
  [ "$RETAIN_DAYS" -gt 0 ] || return 0
  [ -d "$OUT" ] || return 0
  find "$OUT" -maxdepth 1 -type f \
    \( -name 'db-*.sql.zst' -o -name 'data-*.tar.zst' -o -name 'manifest-*.json' \) \
    -mtime +"$RETAIN_DAYS" -delete
}

mkdir -p "$OUT"
if [ "$PRUNE_ONLY" = true ]; then
  prune_old
  exit 0
fi

TS="$(date -u +%Y%m%dT%H%M%SZ)"
COMPOSE=(docker compose -f "$COMPOSE_FILE" ${PROJECT:+-p "$PROJECT"})

backup_done=false
cleanup() {
  if [ "$backup_done" != true ]; then
    rm -f "$OUT/db-$TS.sql.zst" "$OUT/data-$TS.tar.zst" "$OUT/manifest-$TS.json"
  fi
}
trap cleanup EXIT

if [ -n "$PROJECT" ]; then
  PROJ="$PROJECT"
else
  PROJ="$("${COMPOSE[@]}" config --format json | jq -r .name)"
fi
[ -n "$PROJ" ] || { echo "backup.sh: nie udało się ustalić nazwy projektu compose" >&2; exit 1; }

DB_CID="$("${COMPOSE[@]}" ps -q "$DB_SERVICE")"
[ -n "$DB_CID" ] || { echo "backup.sh: kontener usługi $DB_SERVICE nie działa" >&2; exit 1; }
DB_IMAGE="$(docker inspect --format '{{.Config.Image}}' "$DB_CID")"

VOL_NAME="$(docker volume ls -q \
  --filter "label=com.docker.compose.project=$PROJ" \
  --filter "label=com.docker.compose.volume=$DATA_VOLUME")"
[ -n "$VOL_NAME" ] || { echo "backup.sh: nie znaleziono wolumenu $DATA_VOLUME w projekcie $PROJ" >&2; exit 1; }

# 2. Dump bazy — hasło wyłącznie ze środowiska kontenera.
"${COMPOSE[@]}" exec -T "$DB_SERVICE" bash -c 'set -o pipefail; mariadb-dump --single-transaction --routines --hex-blob -uroot -p"$MARIADB_ROOT_PASSWORD" --databases "$MARIADB_DATABASE" | zstd -q -T0' \
  > "$OUT/db-$TS.sql.zst"

# 3. Wolumen danych.
docker run --rm -v "$VOL_NAME":/data:ro --entrypoint sh "$DB_IMAGE" \
  -c 'tar --zstd --numeric-owner -C /data -cf - .' > "$OUT/data-$TS.tar.zst"

[ -s "$OUT/db-$TS.sql.zst" ] || { echo "backup.sh: dump bazy jest pusty" >&2; exit 1; }
[ -s "$OUT/data-$TS.tar.zst" ] || { echo "backup.sh: archiwum wolumenu jest puste" >&2; exit 1; }
docker run --rm -i --entrypoint zstd "$DB_IMAGE" -t < "$OUT/db-$TS.sql.zst"
docker run --rm -i --entrypoint zstd "$DB_IMAGE" -t < "$OUT/data-$TS.tar.zst"

# 4. Wersje: schemat z bazy, wersja WD z obrazu api (gdy niedostępna — "unknown").
ALEMBIC_VERSION="$("${COMPOSE[@]}" exec -T "$DB_SERVICE" sh -c \
  'mariadb -N -B -uroot -p"$MARIADB_ROOT_PASSWORD" "$MARIADB_DATABASE" -e "SELECT version_num FROM alembic_version"' \
  | tr -d '\r' | head -n1)"
WD_VERSION="$("${COMPOSE[@]}" exec -T api python -c 'from app.core.version import APP_VERSION; print(APP_VERSION)' 2>/dev/null || true)"
WD_VERSION="$(printf '%s' "$WD_VERSION" | tr -d '\r\n')"
[ -n "$WD_VERSION" ] || WD_VERSION="unknown"
DB_NAME="$("${COMPOSE[@]}" exec -T "$DB_SERVICE" sh -c 'printf %s "$MARIADB_DATABASE"')"

# 5. Manifest.
DB_SHA="$(sha256sum "$OUT/db-$TS.sql.zst" | cut -d' ' -f1)"
DB_BYTES="$(wc -c < "$OUT/db-$TS.sql.zst" | tr -d ' ')"
DATA_SHA="$(sha256sum "$OUT/data-$TS.tar.zst" | cut -d' ' -f1)"
DATA_BYTES="$(wc -c < "$OUT/data-$TS.tar.zst" | tr -d ' ')"

jq -n \
  --arg ts "$TS" --arg wd "$WD_VERSION" --arg al "$ALEMBIC_VERSION" --arg db "$DB_NAME" \
  --arg dbn "db-$TS.sql.zst" --arg dbsha "$DB_SHA" --argjson dbb "$DB_BYTES" \
  --arg dan "data-$TS.tar.zst" --arg dash "$DATA_SHA" --argjson dab "$DATA_BYTES" \
  '{format: 1, timestamp: $ts, wd_version: $wd, alembic_version: $al, db_name: $db,
    files: {db: {name: $dbn, sha256: $dbsha, bytes: $dbb},
            data: {name: $dan, sha256: $dash, bytes: $dab}}}' \
  > "$OUT/manifest-$TS.json"

# 6. Retencja.
prune_old

backup_done=true
echo "BACKUP_TS=$TS"
