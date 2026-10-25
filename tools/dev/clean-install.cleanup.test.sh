#!/usr/bin/env bash
# Test funkcji cleanup() z tools/dev/clean-install.sh (brief T2 E5-H7b, K1 poprawka 2026-10-05b p. 4).
# Bez Dockera i bez stawiania stosu: wyciąga samą funkcję cleanup() (sed) i uruchamia ją w atrapie:
#   - COMPOSE=(compose-stub) → zapisuje wywołania do $ORDER_LOG (kolejność collect.sh vs down -v),
#   - $ROOT/tools/dev/real/collect.sh → stub zapisujący plik-znacznik i oba argumenty.
# Przypadki:
#   (a) rc=3 → znacznik collect.sh istnieje, ARTIFACTS_DIR jako 2. arg, komunikat na stderr, rc procesu 3;
#   (b) rc=0 → collect.sh niewołany;
#   (c) collect.sh kończy się rc=1 → rc skryptu nadal 3 (best-effort).
# Uruchomienie: bash tools/dev/clean-install.cleanup.test.sh
set -euo pipefail

ROOT_REPO="$(git rev-parse --show-toplevel)"
CLEAN_INSTALL="$ROOT_REPO/tools/dev/clean-install.sh"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
fail() { echo "clean-install.cleanup.test: $*" >&2; exit 1; }

grep -q '^cleanup() {' "$CLEAN_INSTALL" || fail "clean-install.sh: brak funkcji cleanup()"
ARTIFACTS_LINE="$(grep -m1 '^ARTIFACTS_DIR=' "$CLEAN_INSTALL" || true)"
[ -n "$ARTIFACTS_LINE" ] || fail "clean-install.sh: brak zmiennej ARTIFACTS_DIR (kontrakt T2)"

# Atrapa drzewa repo: $FAKE_ROOT/tools/dev/real/collect.sh.
FAKE_ROOT="$TMP/fakeroot"
mkdir -p "$FAKE_ROOT/tools/dev/real"
MARKER="$TMP/marker"
mkdir -p "$MARKER"
ORDER_LOG="$TMP/order.log"

# Stub collect.sh: znacznik + oba argumenty + wpis do ORDER_LOG; kod wyjścia z $COLLECT_EXIT.
{
  echo '#!/usr/bin/env bash'
  echo ': > "$MARKER_DIR/called"'
  echo 'printf "%s\n" "$1" > "$MARKER_DIR/arg1"'
  echo 'printf "%s\n" "$2" > "$MARKER_DIR/arg2"'
  echo 'printf "collect\n" >> "$ORDER_LOG"'
  echo 'exit "${COLLECT_EXIT:-0}"'
} > "$FAKE_ROOT/tools/dev/real/collect.sh"
chmod +x "$FAKE_ROOT/tools/dev/real/collect.sh"

# Atrapa `docker compose` (COMPOSE) zapisująca wywołanie — do sprawdzenia kolejności.
BIN="$TMP/bin"
mkdir -p "$BIN"
printf '%s\n' '#!/usr/bin/env bash' 'printf "compose %s\n" "$*" >> "$ORDER_LOG"' > "$BIN/compose-stub"
chmod +x "$BIN/compose-stub"

# Uruchamia cleanup() przy danym kodzie wyjścia skryptu; ustawia globals ACTUAL_RC, ERR_TEXT, ART.
ART=""
ACTUAL_RC=""
ERR_TEXT=""
run_cleanup() {
  local rc="$1" collect_exit="${2:-0}"
  ART="$TMP/art-$rc-$collect_exit"
  local scratch="$TMP/scratch-$rc-$collect_exit"
  local wrapper="$TMP/wrapper.sh" err="$TMP/err.txt"
  mkdir -p "$scratch"
  : > "$ORDER_LOG"
  rm -f "$MARKER/called" "$MARKER/arg1" "$MARKER/arg2"
  {
    echo '#!/usr/bin/env bash'
    echo 'COMPOSE=(compose-stub)'
    echo "ROOT=\"$FAKE_ROOT\""
    echo 'PROJ="wd-ci-test"'
    echo "TMP=\"$scratch\""
    echo "$ARTIFACTS_LINE"
    sed -n '/^cleanup()/,/^}/p' "$CLEAN_INSTALL"
    echo 'trap cleanup EXIT'
    echo "exit $rc"
  } > "$wrapper"
  local actual=0
  WD_CI_ARTIFACTS_DIR="$ART" MARKER_DIR="$MARKER" COLLECT_EXIT="$collect_exit" \
    ORDER_LOG="$ORDER_LOG" PATH="$BIN:$PATH" bash "$wrapper" 2>"$err" || actual=$?
  ACTUAL_RC="$actual"
  ERR_TEXT="$(cat "$err")"
}

# --- (a) rc=3: artefakty zbierane przed down -v, rc zachowany ---
run_cleanup 3
[ "$ACTUAL_RC" -eq 3 ] || fail "(a) rc=$ACTUAL_RC, oczekiwano 3"
[ -f "$MARKER/called" ] || fail "(a) collect.sh niewołany (brak pliku-znacznika)"
[ "$(cat "$MARKER/arg1")" = "wd-ci-test" ] || fail "(a) 1. arg collect.sh = '$(cat "$MARKER/arg1")', oczekiwano wd-ci-test"
[ "$(cat "$MARKER/arg2")" = "$ART" ] || fail "(a) 2. arg collect.sh = '$(cat "$MARKER/arg2")', oczekiwano ARTIFACTS_DIR=$ART"
if ! grep -q 'artefakty diagnostyczne' <<<"$ERR_TEXT"; then
  fail "(a) stderr bez komunikatu 'artefakty diagnostyczne': $ERR_TEXT"
fi
[ "$(head -1 "$ORDER_LOG")" = "collect" ] || fail "(a) collect.sh nie przed down -v (kolejność: $(tr '\n' ',' <"$ORDER_LOG"))"

# --- (b) rc=0: collect.sh niewołany ---
run_cleanup 0
[ "$ACTUAL_RC" -eq 0 ] || fail "(b) rc=$ACTUAL_RC, oczekiwano 0"
if [ -f "$MARKER/called" ]; then fail "(b) collect.sh wołany przy rc=0"; fi
if grep -q 'artefakty diagnostyczne' <<<"$ERR_TEXT"; then fail "(b) komunikat artefaktów przy rc=0"; fi

# --- (c) collect.sh rc=1 nie zmienia rc skryptu ---
run_cleanup 3 1
[ "$ACTUAL_RC" -eq 3 ] || fail "(c) rc=$ACTUAL_RC po collect.sh rc=1, oczekiwano 3"
[ -f "$MARKER/called" ] || fail "(c) collect.sh niewołany"

echo "clean-install.cleanup.test: OK (rc≠0 → artefakty przed down -v, rc zachowany; rc=0 → bez zbierania)"
