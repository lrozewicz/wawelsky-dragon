#!/usr/bin/env bash
# Wyrocznia T6 (WP E4-3d): `tools/dev/up.sh test seed` na realnym stosie testowym.
# Stawia izolowany stos tego worktree, woła seed, sprawdza 5 linii wyjścia (C7) i loguje się
# danymi z seedu przez POST /api/v1/auth/login (oczekiwany `code: 0`).
# Zawsze sprząta — trap woła `up.sh test down`, czyli `down -v` WYŁĄCZNIE na własnym projekcie compose.
set -euo pipefail
ROOT="$(git rev-parse --show-toplevel)"; cd "$ROOT"
UP="$ROOT/tools/dev/up.sh"

cleanup() { "$UP" test down >/dev/null 2>&1 || true; }
trap cleanup EXIT
fail() { echo "up-seed: $*" >&2; exit 1; }

"$UP" test up mariadb-test migrate api
OUT="$("$UP" test seed)"

mapfile -t LINES <<<"$OUT"
[ "${#LINES[@]}" -eq 5 ] || fail "seed: oczekiwano 5 linii, dostałem ${#LINES[@]}: $OUT"
[[ "${LINES[0]}" == UI_URL=http://* ]] || fail "seed: linia 1: ${LINES[0]}"
[[ "${LINES[1]}" == API_URL=http://* ]] || fail "seed: linia 2: ${LINES[1]}"
[[ "${LINES[2]}" == ADMIN_EMAIL=*@* ]] || fail "seed: linia 3: ${LINES[2]}"
[[ "${LINES[3]}" == "ADMIN_PASSWORD=wd-test-admin-1" ]] || fail "seed: linia 4: ${LINES[3]}"
[[ "${LINES[4]}" == API_KEY=ragflow-* ]] || fail "seed: linia 5: ${LINES[4]}"

API_URL="${LINES[1]#API_URL=}"
ADMIN_EMAIL="${LINES[2]#ADMIN_EMAIL=}"
ADMIN_PASSWORD="${LINES[3]#ADMIN_PASSWORD=}"

BODY="$(curl -sS --max-time 30 -X POST -H 'Content-Type: application/json' \
  -d "{\"email\":\"$ADMIN_EMAIL\",\"password\":\"$ADMIN_PASSWORD\"}" \
  "$API_URL/api/v1/auth/login")" || fail "login: curl nie powiódł się"
python3 -c 'import json,sys; sys.exit(0 if json.loads(sys.argv[1]).get("code") == 0 else 1)' "$BODY" \
  || fail "login: code != 0: $BODY"

echo "up-seed: OK (5 linii seedu + login code 0)"
