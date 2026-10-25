#!/usr/bin/env bash
# Kontrolna mutacja Reviewera (analiza 2026-10-11: Reviewer GLM odrzucał ~6% wersji, „test, który nie testuje” przechodził).
# Lekka wersja tools/dev/mutation-check.sh: bez stosu Dockera, dla testów jednostkowych frontu i backendu.
#
#   tools/dev/review-mutation.sh --sed <plik> '<wyrażenie sed>' -- <komenda testu>
#   tools/dev/review-mutation.sh --patch <łatka.patch> -- <komenda testu>
#
#   <plik>          ścieżka względem korzenia repo, np. backend/app/llm/rate_limit.py (bezwzględna → zamieniana na względną)
#   <wyrażenie sed> JEDNA zmiana psująca logikę, np. 's/attempt < MAX/attempt <= MAX/'
#   <komenda testu> uruchamiana w korzeniu kopii, np. `cd backend && uv run --frozen pytest -q tests/unit/llm/test_rate_limit.py`
#                   albo `cd frontend && bunx vitest run src/features/x/X.test.tsx`
#
# Nie dotyka drzewa roboczego Reviewera ani Programisty: kopia HEAD w /tmp (git worktree --detach), node_modules
# podlinkowane z bieżącego worktree, .venv backendu zakłada uv z cache. Sprząta zawsze.
# Kod wyjścia: 0 — mutacja WYKRYTA (testy czerwone), 1 — mutacja PRZEŻYŁA (testy zielone mimo błędu = MAJOR),
#              (przekroczenie WD_MUT_TIMEOUT_S, dom. 600 s, z mutacją liczy się jako WYKRYTA z ostrzeżeniem)
#              2 — wynik nieważny (testy czerwone bez mutacji, sed niczego nie zmienił, łatka się nie nakłada, błąd).
set -uo pipefail
MODE="${1:-}"; shift || true
case "$MODE" in
  --sed) FILE="${1:-}"; EXPR="${2:-}"; shift 2 || true ;;
  --patch) PATCH="$(readlink -f "${1:-}")"; shift || true ;;
  *) echo "użycie: $0 --sed <plik> '<sed>' -- <test> | --patch <łatka> -- <test>" >&2; exit 2 ;;
esac
[ "${1:-}" = "--" ] && shift
[ "$#" -ge 1 ] || { echo "brak komendy testu po --" >&2; exit 2; }
TEST_CMD="$*"

SRC="$(git rev-parse --show-toplevel)" || exit 2
WT="$(mktemp -d /tmp/rev-mut.XXXXXX)"; rmdir "$WT"
cleanup() { git -C "$SRC" worktree remove --force "$WT" >/dev/null 2>&1 || rm -rf "$WT"; }
trap cleanup EXIT
git -C "$SRC" worktree add --detach "$WT" HEAD >/dev/null 2>&1 || { echo "WYNIK NIEWAŻNY: nie udało się założyć kopii HEAD"; exit 2; }
[ -d "$SRC/frontend/node_modules" ] && [ -d "$WT/frontend" ] && ln -s "$SRC/frontend/node_modules" "$WT/frontend/node_modules"
cd "$WT" || exit 2

# Limit czasu testu (2026-10-12: test pod mutacją zawisł bez końca). Przekroczenie z mutacją = testy jej nie przepuściły.
LIMIT="${WD_MUT_TIMEOUT_S:-600}"
run() { timeout --kill-after=10 "$LIMIT" bash -c "$TEST_CMD" >"$WT.log" 2>&1; }

echo "--- bez mutacji (oczekiwane: zielone): $TEST_CMD"
run; rc=$?
if [ "$rc" -ne 0 ]; then tail -15 "$WT.log"; [ "$rc" -eq 124 ] && echo "WYNIK NIEWAŻNY: testy bez mutacji przekroczyły ${LIMIT} s" || echo "WYNIK NIEWAŻNY: testy czerwone już bez mutacji"; rm -f "$WT.log"; exit 2; fi

if [ "$MODE" = --sed ]; then
  # Ścieżka bezwzględna wskazywałaby ORYGINAŁ, nie kopię w /tmp (2026-10-12: mutacja trafiła do worktree Programisty).
  # Zamieniamy ją na względną wobec korzenia źródła; spoza repo — odmowa.
  case "$FILE" in
    /*) REAL="$(readlink -f "$FILE")"; SRCR="$(readlink -f "$SRC")"
        case "$REAL" in "$SRCR"/*) FILE="${REAL#"$SRCR"/}" ;;
          *) echo "WYNIK NIEWAŻNY: plik $FILE poza repo $SRC — podaj ścieżkę względną"; exit 2 ;; esac ;;
  esac
  case "$FILE" in *..*) echo "WYNIK NIEWAŻNY: ścieżka z .. niedozwolona"; exit 2 ;; esac
  [ -f "$FILE" ] || { echo "WYNIK NIEWAŻNY: brak pliku $FILE"; exit 2; }
  cp "$FILE" "$WT.orig"; sed -i -e "$EXPR" "$FILE"
  if cmp -s "$FILE" "$WT.orig"; then rm -f "$WT.orig" "$WT.log"; echo "WYNIK NIEWAŻNY: sed niczego nie zmienił w $FILE"; exit 2; fi
  echo "--- mutacja ($FILE):"; diff -u "$WT.orig" "$FILE" | sed -n '3,12p'; rm -f "$WT.orig"
else
  git apply "$PATCH" || { echo "WYNIK NIEWAŻNY: łatka się nie nakłada"; exit 2; }
  echo "--- mutacja: $(basename "$PATCH")"
fi

echo "--- z mutacją (oczekiwane: czerwone)"
run; rc=$?
if [ "$rc" -eq 0 ]; then rm -f "$WT.log"; echo "MUTACJA PRZEŻYŁA — testy nie wykrywają tej zmiany (MAJOR: test, który nie testuje)"; exit 1; fi
[ "$rc" -eq 124 ] && echo "--- testy z mutacją przekroczyły ${LIMIT} s (zawieszenie) — mutacja nie przeszła niezauważona, ale sprawdź, czy test nie powinien paść szybciej"
grep -E "failed|FAIL|AssertionError|Error" "$WT.log" | head -5; rm -f "$WT.log"
echo "MUTACJA WYKRYTA — testy czerwone"; exit 0
