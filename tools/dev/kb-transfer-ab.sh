#!/usr/bin/env bash
# Wyrocznia T9 (WP E7-2, brief): scenariusz SC-E7-2-06 — transfer bazy wiedzy A → B na DWOCH
# stosach clean-install (R-KB-01 kroki 1–8). DWA biegi:
#   1. WD_KBAB_PHASE=export WD_CI_SPEC=kb-transfer-ab.spec.ts — stos A: baza z rocznikiem GUS
#      i DOCX, parsowanie do „Sukces”, edycja i wyłączenie chunku w UI, eksport w UI; paczka
#      package.wdkb.zip i state.json trafiają do $WD_KBAB_DIR;
#   2. WD_KBAB_PHASE=import (tylko po zielonym biegu 1) — świeży stos B: import paczki w UI,
#      czat/retrieval z cytatem, edycja i wyłączenie zachowane.
# Kod wyjścia = pierwszy niezerowy kod biegu (drugi bieg nie startuje po czerwieni pierwszego);
# log idzie na stdout. Uruchamiać WYŁĄCZNIE na wyłączność (reguła README frontend/e2e-real) —
# guard niżej sprawdza dostępną pamięć (≥ 12 GiB) i brak innych stosów wd-ci-*.
#   tools/dev/kb-transfer-ab.sh
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel)"; cd "$ROOT"

# Korpus jak w mcp-prod-check.sh: katalog dataset/documents/pl obok GŁÓWNEGO checkoutu (worktree
# czyta korpus z katalogu hosta); spec bierze z niego rocznik GUS (fallback fixture) i DOCX.
MAIN_ROOT="$(dirname "$(readlink -f "$(git rev-parse --git-common-dir)")")"
export WD_REAL_CORPUS="${WD_REAL_CORPUS:-$MAIN_ROOT/../dataset/documents/pl}"
export WD_REAL_OUT="${WD_REAL_OUT:-$ROOT/test-results-real/report}"
mkdir -p "$WD_REAL_OUT"

# Katalog wymiany między biegami (paczka + state.json); czyszczony na starcie (brief T9).
export WD_KBAB_DIR="$WD_REAL_OUT/kb-transfer-ab"
rm -rf -- "$WD_KBAB_DIR"
mkdir -p "$WD_KBAB_DIR"

# Guard wyłączności: pamięć (brief) i brak biegu clean-install innego worktree.
AVAIL_GIB="$(free -g | awk '/^Mem:/ {print $7}')"
if [ "${AVAIL_GIB:-0}" -lt 12 ]; then
  echo "kb-transfer-ab: dostępne ${AVAIL_GIB} GiB pamięci, wymagane ≥ 12 (free -g)" >&2
  exit 3
fi
if docker ps --format '{{.Names}}' | grep -q '^wd-ci-'; then
  echo "kb-transfer-ab: działa inny stos wd-ci-* — wyrocznia na wyłączność (docker ps)" >&2
  exit 3
fi

rc=0
echo "[kb-transfer-ab] bieg 1/2: stos A — faza export (SC-E7-2-06)"
WD_KBAB_PHASE=export WD_CI_SPEC=kb-transfer-ab.spec.ts "$ROOT/tools/dev/clean-install.sh" || rc=$?

if [ "$rc" -eq 0 ]; then
  echo "[kb-transfer-ab] bieg 2/2: stos B — faza import (SC-E7-2-06)"
  WD_KBAB_PHASE=import WD_CI_SPEC=kb-transfer-ab.spec.ts "$ROOT/tools/dev/clean-install.sh" || rc=$?
fi

if [ "$rc" -eq 0 ]; then
  echo "[kb-transfer-ab] oba biegi zielone"
fi
exit "$rc"