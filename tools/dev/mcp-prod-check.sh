#!/usr/bin/env bash
# Wyrocznia T8 (WP E6-2, brief): scenariusze MCP SC-E6-2-01…05 i 07 przez proxy `web` na
# produkcyjnym stosie clean-install — DWA biegi:
#   1. WD_CI_PROFILES=mcp WD_CI_SPEC=mcp-prod.spec.ts — cały łańcuch klient → web → mcp → api
#      (streamable HTTP i SSE, izolacja użytkowników, 401/Unauthorized, 20 równoległych + RSS);
#   2. WD_CI_SPEC=mcp-off.spec.ts — stos bez profilu `mcp`: 503 z treścią K17 §1, web zdrowy.
# Kod wyjścia = pierwszy niezerowy kod biegu (drugi bieg nie startuje po czerwieni pierwszego);
# log idzie na stdout. Uruchamiać WYŁĄCZNIE na wyłączność (reguła README frontend/e2e-real) —
# guard niżej sprawdza dostępną pamięć (≥ 12 GiB) i brak innych stosów wd-ci-*.
#   tools/dev/mcp-prod-check.sh
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel)"; cd "$ROOT"

# Korpus jak w verify-real.sh: katalog dataset/documents/pl obok GŁÓWNEGO checkoutu (worktree
# czyta korpus z katalogu hosta); spec mcp-prod bierze z niego najmniejszy PDF.
MAIN_ROOT="$(dirname "$(readlink -f "$(git rev-parse --git-common-dir)")")"
export WD_REAL_CORPUS="${WD_REAL_CORPUS:-$MAIN_ROOT/../dataset/documents/pl}"
export WD_REAL_OUT="${WD_REAL_OUT:-$ROOT/test-results-real/report}"
mkdir -p "$WD_REAL_OUT"

# Guard wyłączności: pamięć (brief) i brak biegu clean-install innego worktree.
AVAIL_GIB="$(free -g | awk '/^Mem:/ {print $7}')"
if [ "${AVAIL_GIB:-0}" -lt 12 ]; then
  echo "mcp-prod-check: dostępne ${AVAIL_GIB} GiB pamięci, wymagane ≥ 12 (free -g)" >&2
  exit 3
fi
if docker ps --format '{{.Names}}' | grep -q '^wd-ci-'; then
  echo "mcp-prod-check: działa inny stos wd-ci-* — wyrocznia na wyłączność (docker ps)" >&2
  exit 3
fi

rc=0
echo "[mcp-prod-check] bieg 1/2: profil mcp — SC-E6-2-01…04, 07"
WD_CI_PROFILES=mcp WD_CI_SPEC=mcp-prod.spec.ts "$ROOT/tools/dev/clean-install.sh" || rc=$?

if [ "$rc" -eq 0 ]; then
  echo "[mcp-prod-check] bieg 2/2: bez profilu — SC-E6-2-05"
  WD_CI_SPEC=mcp-off.spec.ts "$ROOT/tools/dev/clean-install.sh" || rc=$?
fi

if [ "$rc" -eq 0 ]; then
  echo "[mcp-prod-check] oba biegi zielone"
fi
exit "$rc"
