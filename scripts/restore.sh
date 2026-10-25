#!/usr/bin/env bash
# restore.sh — odtworzenie kopii B1 z weryfikacją sha256 i wersji schematu (kontrakt WP E5-3 C4).
#
# Użycie:
#   scripts/restore.sh --out DIR --ts TS [--compose-file FILE] [--project NAME] [--db-service SVC]
#                      [--data-volume VOL] [--app-services "api worker"] [--migrate-service NAME]
#
# Domyślnie: --compose-file docker-compose.yml (względem korzenia repo), --db-service mariadb,
# --data-volume app-data, --app-services "api worker", --migrate-service migrate.
# Weryfikacja sha256 i wersji schematu odbywa się PRZED zatrzymaniem czegokolwiek.
# Hasło root MariaDB jest czytane wyłącznie wewnątrz kontenera (ze środowiska kontenera).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

usage() {
  echo "użycie: restore.sh --out DIR --ts TS [--compose-file FILE] [--project NAME] [--db-service SVC]" >&2
  echo "                    [--data-volume VOL] [--app-services \"api worker\"] [--migrate-service NAME]" >&2
}

OUT=""
TS=""
COMPOSE_FILE="$ROOT/docker-compose.yml"
PROJECT=""
DB_SERVICE="mariadb"
DATA_VOLUME="app-data"
APP_SERVICES="api worker"
MIGRATE_SERVICE="migrate"

while [ $# -gt 0 ]; do
  case "$1" in
    --out|--ts|--compose-file|--project|--db-service|--data-volume|--app-services|--migrate-service)
      [ $# -ge 2 ] || { usage; exit 2; }
      case "$1" in
        --out) OUT="$2" ;;
        --ts) TS="$2" ;;
        --compose-file) COMPOSE_FILE="$2" ;;
        --project) PROJECT="$2" ;;
        --db-service) DB_SERVICE="$2" ;;
        --data-volume) DATA_VOLUME="$2" ;;
        --app-services) APP_SERVICES="$2" ;;
        --migrate-service) MIGRATE_SERVICE="$2" ;;
      esac
      shift 2
      ;;
    *)
      usage
      exit 2
      ;;
  esac
done

[ -n "$OUT" ] && [ -n "$TS" ] || { usage; exit 2; }

MANIFEST="$OUT/manifest-$TS.json"
[ -f "$MANIFEST" ] || { echo "restore.sh: brak manifestu $MANIFEST" >&2; exit 1; }

# 1. Weryfikacja sum PRZED jakąkolwiek zmianą stanu (jeszcze bez wywołań Dockera).
for key in db data; do
  NAME="$(jq -r --arg k "$key" '.files[$k].name' "$MANIFEST")"
  WANT="$(jq -r --arg k "$key" '.files[$k].sha256' "$MANIFEST")"
  [ -f "$OUT/$NAME" ] || { echo "restore.sh: brak pliku $NAME" >&2; exit 1; }
  GOT="$(sha256sum "$OUT/$NAME" | cut -d' ' -f1)"
  [ "$GOT" = "$WANT" ] || { echo "sha256 mismatch: $NAME" >&2; exit 3; }
done

DB_NAME="$(jq -r .db_name "$MANIFEST")"
case "$DB_NAME" in
  ''|*[!A-Za-z0-9_]*) echo "restore.sh: nieprawidłowa nazwa bazy w manifeście" >&2; exit 1 ;;
esac

COMPOSE=(docker compose -f "$COMPOSE_FILE" ${PROJECT:+-p "$PROJECT"})

# 2. Wersja schematu: manifest > head obrazu → kopia nowsza niż obraz (przed zmianą stanu).
BACKUP_ALEMBIC="$(jq -r .alembic_version "$MANIFEST")"
case "$BACKUP_ALEMBIC" in
  ''|*[!0-9]*) echo "restore.sh: nieprawidłowa alembic_version w manifeście" >&2; exit 1 ;;
esac
SCHEMA_HEAD="$("${COMPOSE[@]}" run --rm --no-deps --entrypoint python "$MIGRATE_SERVICE" \
  -c 'from app.db.schema import SCHEMA_HEAD; print(SCHEMA_HEAD)' | tr -d '\r' | head -n1)"
case "$SCHEMA_HEAD" in
  ''|*[!0-9]*) echo "restore.sh: nie udało się ustalić wersji schematu obrazu" >&2; exit 1 ;;
esac
if [ "$((10#$BACKUP_ALEMBIC))" -gt "$((10#$SCHEMA_HEAD))" ]; then
  echo "backup is newer than image" >&2
  exit 4
fi

if [ -n "$PROJECT" ]; then
  PROJ="$PROJECT"
else
  PROJ="$("${COMPOSE[@]}" config --format json | jq -r .name)"
fi
[ -n "$PROJ" ] || { echo "restore.sh: nie udało się ustalić nazwy projektu compose" >&2; exit 1; }

# 3. Baza w górę, aplikacje w dół (usługi nieistniejące w pliku compose pomijamy).
"${COMPOSE[@]}" up -d --wait "$DB_SERVICE"
EXISTING_SERVICES="$("${COMPOSE[@]}" config --services)"
STOP_SERVICES=()
for svc in $APP_SERVICES web; do
  if grep -qx "$svc" <<<"$EXISTING_SERVICES"; then
    STOP_SERVICES+=("$svc")
  fi
done
if [ "${#STOP_SERVICES[@]}" -gt 0 ]; then
  "${COMPOSE[@]}" stop "${STOP_SERVICES[@]}"
fi

# 4. Odtworzenie bazy: DROP + import dumpu (dump z --databases zawiera CREATE DATABASE i USE).
"${COMPOSE[@]}" exec -T "$DB_SERVICE" sh -c 'mariadb -uroot -p"$MARIADB_ROOT_PASSWORD" -e "DROP DATABASE IF EXISTS \`$1\`"' _ "$DB_NAME"
DB_FILE="$(jq -r .files.db.name "$MANIFEST")"
"${COMPOSE[@]}" exec -T "$DB_SERVICE" bash -c 'set -o pipefail; zstd -dc | mariadb -uroot -p"$MARIADB_ROOT_PASSWORD"' < "$OUT/$DB_FILE"

# 5. Odtworzenie wolumenu danych.
VOL_NAME="$(docker volume ls -q \
  --filter "label=com.docker.compose.project=$PROJ" \
  --filter "label=com.docker.compose.volume=$DATA_VOLUME")"
if [ -z "$VOL_NAME" ]; then
  FIRST_APP="${APP_SERVICES%% *}"
  "${COMPOSE[@]}" create "$FIRST_APP"
  VOL_NAME="$(docker volume ls -q \
    --filter "label=com.docker.compose.project=$PROJ" \
    --filter "label=com.docker.compose.volume=$DATA_VOLUME")"
fi
[ -n "$VOL_NAME" ] || { echo "restore.sh: nie znaleziono wolumenu $DATA_VOLUME w projekcie $PROJ" >&2; exit 1; }
DB_IMAGE="$(docker inspect --format '{{.Config.Image}}' "$("${COMPOSE[@]}" ps -q "$DB_SERVICE")")"
DATA_FILE="$(jq -r .files.data.name "$MANIFEST")"
docker run --rm -i -v "$VOL_NAME":/data --entrypoint sh "$DB_IMAGE" \
  -c 'find /data -mindepth 1 -delete && tar --zstd --numeric-owner -C /data -xpf -' < "$OUT/$DATA_FILE"

# 6. Migracje, aplikacje w górę i kontrola /health/ready.
"${COMPOSE[@]}" run --rm --no-deps "$MIGRATE_SERVICE"
# `--no-deps`: migracje właśnie przeszły jawnym `run --rm migrate` wyżej, więc ten `up` nie ma po co
# uruchamiać kontenera `migrate` po raz drugi (T6: drugie uruchomienie potrafiło wyjść kodem 1 —
# `Container …-migrate-1 Error service "migrate" didn't complete successfully: exit 1`). Przy okazji
# `up` nie sięga wtedy po zależności, więc nie wymieni kontenera bazy (tmpfs!), którego dane z dumpu
# dopiero co zostały odtworzone — a wymianę potrafi wyzwolić zmiana obrazu pod wspólnym tagiem.
"${COMPOSE[@]}" up -d --wait --no-deps $APP_SERVICES
"${COMPOSE[@]}" exec -T api python -c "import urllib.request,sys;sys.exit(0 if urllib.request.urlopen('http://localhost:8000/health/ready',timeout=5).status==200 else 1)"

echo "RESTORE_OK $TS"
