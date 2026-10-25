#!/usr/bin/env bash
# Test tools/dev/real/collect.sh bez Dockera (brief T1 E5-H6c): atrapa `docker` w PATH
# (dla `ps` zwraca cid, dla reszty stałe logi z sekretem) i fałszywy projekt wd-ci-*.
# Sprawdza komplet artefaktów, brak wycieku hasła i kod wyjścia 2 dla obcego projektu.
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel)"
COLLECT="$ROOT/tools/dev/real/collect.sh"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
fail() { echo "collect.test: $*" >&2; exit 1; }

BIN="$TMP/bin"
mkdir -p "$BIN"

# Atrapa docker: dla `ps` zwraca cid, dla reszty stałe logi (z sekretem do zamaskowania).
printf '%s\n' \
  '#!/usr/bin/env sh' \
  'if [ "$1" = "ps" ]; then' \
  '  echo abc123' \
  '  exit 0' \
  'fi' \
  'echo "2026-01-01T00:00:00Z worker WD_DB_PASSWORD=sekret123 WD_SECRET_KEY=tajne"' \
  'echo "2026-01-01T00:00:01Z worker gotowe"' \
  > "$BIN/docker"
chmod +x "$BIN/docker"

OUT="$TMP/out"
PATH="$BIN:$PATH" bash "$COLLECT" wd-ci-x "$OUT"

for f in worker.log api.log mariadb.log worker-inspect.txt tasks.tsv documents.tsv worker_heartbeat.tsv README.txt; do
  [ -f "$OUT/$f" ] || fail "brak pliku $f"
done

grep -rq sekret123 "$OUT" && fail "sekret wyciekł do artefaktów"

rc=0
PATH="$BIN:$PATH" bash "$COLLECT" zly-projekt "$TMP/zly" >/dev/null 2>&1 || rc=$?
[ "$rc" -eq 2 ] || fail "zły projekt → rc=$rc, oczekiwano 2"

echo "collect.test: OK (komplet artefaktów, brak wycieku sekretu, obcy projekt rc 2)"
