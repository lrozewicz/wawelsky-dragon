#!/usr/bin/env bash
# Test negatywny strażnika łatek mutacyjnych (WP E7-H1, zadanie T1).
# Sprawdzian `tools/dev/tests/mutations-apply.sh` MUSI wykryć łatkę, która nie nakłada się na HEAD
# (rc 1 + nazwa łatki w wyjściu), NIE MOŻE fałszywie alarmować przy łatce poprawnej i MUSI odmówić
# (rc 2), gdy katalogu łatek nie ma. Katalog podmieniamy przez WD_MUTATIONS_DIR.
# Mini-katalogi w `mktemp -d`, sprzątane; bez Dockera, sieci i commitów
# (wzór: `tools/publish/tests/check-negative.sh`, `tools/dev/tests/mutation-timeout.sh`).
# Kod wyjścia: 0 = wszystkie przypadki zgodne z oczekiwaniem; 1 = niezgodność; 2 = brak danych wejściowych.
set -euo pipefail
ROOT="$(git rev-parse --show-toplevel)"; cd "$ROOT"
GUARD="$ROOT/tools/dev/tests/mutations-apply.sh"
[ -f "$GUARD" ] || { echo "mutations-apply-negative: brak sprawdzianu $GUARD" >&2; exit 2; }
fail() { echo "mutations-apply-negative: $*" >&2; exit 1; }

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
out="$tmp/out.txt"

# (a) łatka z kontekstem, którego w pliku nie ma → rc 1, nazwa łatki i komunikat w wyjściu.
mkdir -p "$tmp/broken"
{
  printf '%s\n' 'diff --git a/backend/app/main.py b/backend/app/main.py'
  printf '%s\n' '--- a/backend/app/main.py' '+++ b/backend/app/main.py'
  printf '%s\n' '@@ -1,3 +1,4 @@' '+NOPE'
  printf '%s\n' ' linia, której w tym pliku nie ma' ' druga taka linia' ' trzecia taka linia'
} > "$tmp/broken/nie-naklada-sie.patch"
rc=0
WD_MUTATIONS_DIR="$tmp/broken" bash "$GUARD" > "$out" 2>&1 || rc=$?
[ "$rc" -eq 1 ] || fail "(a) rc=$rc zamiast 1 dla nienakładającej się łatki ($(tr '\n' ' ' < "$out"))"
grep -q 'NIE NAKŁADA SIĘ' "$out" || fail "(a) brak komunikatu 'NIE NAKŁADA SIĘ' ($(tr '\n' ' ' < "$out"))"
grep -q 'nie-naklada-sie.patch' "$out" || fail "(a) brak nazwy łatki w wyjściu ($(tr '\n' ' ' < "$out"))"
echo "OK: (a) nienakładająca się łatka → rc 1 z nazwą pliku"

# (b) łatka poprawna (kontekst generowany z pliku, więc zawsze aktualny) → rc 0 bez fałszywego alarmu.
mkdir -p "$tmp/ok"
{
  printf '%s\n' 'diff --git a/backend/app/main.py b/backend/app/main.py'
  printf '%s\n' '--- a/backend/app/main.py' '+++ b/backend/app/main.py'
  printf '%s\n' '@@ -1,2 +1,3 @@' '+# MUTACJA: linia dokładana przez łatkę testową'
  sed -n '1,2p' backend/app/main.py | sed 's/^/ /'
} > "$tmp/ok/naklada-sie.patch"
rc=0
WD_MUTATIONS_DIR="$tmp/ok" bash "$GUARD" > "$out" 2>&1 || rc=$?
[ "$rc" -eq 0 ] || fail "(b) rc=$rc zamiast 0 dla poprawnej łatki ($(tr '\n' ' ' < "$out"))"
grep -q 'mutations-apply: 1 łatek OK' "$out" || fail "(b) brak linii licznika ($(tr '\n' ' ' < "$out"))"
echo "OK: (b) nakładająca się łatka → rc 0 i 'mutations-apply: 1 łatek OK'"

# (c) brak katalogu łatek → rc 2 (błąd środowiska, nie „wszystko OK”).
rc=0
WD_MUTATIONS_DIR="$tmp/nie-ma" bash "$GUARD" > "$out" 2>&1 || rc=$?
[ "$rc" -eq 2 ] || fail "(c) rc=$rc zamiast 2 dla brakującego katalogu ($(tr '\n' ' ' < "$out"))"
echo "OK: (c) brak katalogu łatek → rc 2"

# (d) prawdziwy katalog łatek w repo — strażnik musi być zielony (kontrola dodatnia).
rc=0
bash "$GUARD" > "$out" 2>&1 || rc=$?
[ "$rc" -eq 0 ] || fail "(d) prawdziwy katalog łatek czerwony ($(tr '\n' ' ' < "$out"))"
echo "OK: (d) $(grep -o 'mutations-apply: [0-9]* łatek OK' "$out")"
