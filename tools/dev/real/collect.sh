#!/usr/bin/env bash
# Artefakty diagnostyczne stosu WD przy porażce testu odporności (kontrakt WP E5-H6c §K3).
#   collect.sh <projekt wd-ci-*> <katalog_wyjściowy>
# Zbiera logi i stan usług projektu compose; każdy krok jest best-effort — awaria jednego nie
# przerywa pozostałych, a skrypt kończy się 0, gdy katalog wyjściowy powstał.
# Woła go frontend/e2e-real/real-resilience.spec.ts przez `execFileSync` (nigdy shell).
set -uo pipefail

PROJ="${1:-}"
OUT="${2:-}"

# Guard: ruszamy wyłącznie stos tymczasowy clean-install.sh (projekt wd-ci-*), jak kill.sh.
case "$PROJ" in
  wd-ci-*) ;;
  *)
    echo "collect.sh: nazwa projektu musi pasować do wd-ci-* (dostałem '$PROJ')" >&2
    exit 2
    ;;
esac

[ -n "$OUT" ] || { echo "collect.sh: brak katalogu wyjściowego" >&2; exit 2; }
mkdir -p "$OUT" || exit 1

# Maskowanie sekretów: wartości po PASSWORD/SECRET/API_KEY/TOKEN nigdy nie trafiają do plików.
SECRET_RE='s/(PASSWORD|SECRET|API_KEY|TOKEN)=[^ "]+/\1=***/Ig'

# cid (pierwszy) kontenera usługi w projekcie compose.
cid_of() {
  docker ps -a -q \
    --filter "label=com.docker.compose.project=$PROJ" \
    --filter "label=com.docker.compose.service=$1" 2>/dev/null | head -1
}

# Uruchamia komendę, zapisuje stdout+stderr do pliku z zamaskowanymi sekretami. Best-effort.
capture() {
  local file="$1"
  shift
  "$@" 2>&1 | sed -E "$SECRET_RE" > "$OUT/$file" || true
}

# docker logs usługi (stdout+stderr) albo pusty plik, gdy kontenera nie ma.
dump_logs() {
  local svc="$1" file="$2" cid
  cid="$(cid_of "$svc")"
  if [ -n "$cid" ]; then
    capture "$file" docker logs --timestamps "$cid"
  else
    : > "$OUT/$file"
  fi
}

# Wynik zapytania SQL z kontenera mariadb. Zmienne MARIADB_* rozwija shell WEWNĄTRZ kontenera,
# więc hasło nie trafia ani do argumentów, ani na stdout; zapytanie idzie jako "$1" (bez interpolacji).
dump_sql() {
  local file="$1" query="$2" cid
  cid="$(cid_of mariadb)"
  if [ -n "$cid" ]; then
    capture "$file" docker exec "$cid" sh -c \
      'mariadb -u"$MARIADB_USER" -p"$MARIADB_PASSWORD" "$MARIADB_DATABASE" -B -e "$1"' sh "$query"
  else
    : > "$OUT/$file"
  fi
}

dump_logs worker worker.log
dump_logs api api.log
dump_logs mariadb mariadb.log

# Stan workera: RestartCount/Hostname/State. Celowo bez Config.Env (sekrety!).
worker_cid="$(cid_of worker)"
if [ -n "$worker_cid" ]; then
  capture worker-inspect.txt docker inspect \
    --format 'RestartCount={{.RestartCount}} Hostname={{.Config.Hostname}} State={{json .State}}' \
    "$worker_cid"
else
  : > "$OUT/worker-inspect.txt"
fi

# Kolumny wg DDL backend/alembic/versions/0001_initial.py. Tabela `documents` nie ma kolumny
# `chunk_num` (jest `chunk_count`), więc dla niej bierzemy SELECT * (brief T1 p. 18).
dump_sql tasks.tsv 'SELECT public_id, task_type, status, attempts, max_attempts, progress, locked_by, heartbeat_at, next_attempt_at, error, document_id FROM tasks ORDER BY id'
dump_sql documents.tsv 'SELECT * FROM documents'
dump_sql worker_heartbeat.tsv 'SELECT * FROM worker_heartbeat'

# README: znacznik czasu + lista plików w katalogu.
{
  echo "collect.sh: artefakty diagnostyczne projektu $PROJ"
  echo "wygenerowano: $(date -Is)"
  echo "katalog: $OUT"
  echo "pliki:"
  for f in "$OUT"/*; do
    [ -f "$f" ] && echo "- $(basename "$f")"
  done
} > "$OUT/README.txt"

exit 0
