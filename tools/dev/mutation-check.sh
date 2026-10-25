#!/usr/bin/env bash
# Test negatywny (mutacyjny): czy testy wykrywają celowo wprowadzony błąd — zwłaszcza w kodzie bezpieczeństwa.
#
#   tools/dev/mutation-check.sh <łatka> <test pytest> [<test pytest>...]
#     <łatka>  plik z backend/tests/mutations/ (git diff względem korzenia repo), np. auth-token-version.patch
#     <test>   identyfikator pytest względem backend/, np. tests/integration/auth/test_auth_flow.py::test_x
#
# Mutacja NIE dotyka drzewa roboczego: skrypt zakłada tymczasowy worktree `.wp/mut-*` z HEAD (tylko zacommitowany kod),
# stawia tam izolowany stos testowy (tools/dev/up.sh test), uruchamia testy BEZ mutacji (muszą być zielone),
# nakłada łatkę, uruchamia je ponownie (muszą być czerwone), a na koniec zawsze sprząta stos i worktree.
#
# Każde uruchomienie testów idzie pod `timeout` z limitem WD_MUTATION_TIMEOUT_S (domyślnie 900 s) — zawieszony
# test nie wiesza wyroczni bez końca (tools/dev/mutation-lib.sh, test: tools/dev/tests/mutation-timeout.sh).
#
# Kod wyjścia: 0 — mutacja wykryta (testy czerwone), 1 — mutacja PRZEŻYŁA (testy zielone mimo błędu),
#              2 — wynik nieważny (testy czerwone już bez mutacji, łatka się nie nakłada, brak testów, błąd stosu,
#                  przekroczony limit czasu bez mutacji),
#              3 — MUTACJA: TIMEOUT (limit czasu przekroczony w fazie z mutacją; rc 124, albo 137 gdy drzewo
#                  testów trzeba było ubić SIGKILL-em z `--kill-after`).
set -uo pipefail
[ "$#" -ge 2 ] || { echo "użycie: $0 <łatka> <test pytest> [<test>...]" >&2; exit 2; }
ROOT="$(git rev-parse --show-toplevel)"
# Tag obrazów per worktree (WP E4-H3, kontrakt C5): wyeksportuj tag korzenia RODZICA przed
# założeniem worktree .wp/mut-* — inaczej up.sh w mut-worktree użyłby nieistniejącego tagu.
. "$ROOT/tools/dev/wd-version.sh"
wd_export_version "$ROOT"
# Limity czasu i klasyfikacja rc (testowalne bez stosu docker).
. "$ROOT/tools/dev/mutation-lib.sh"
PATCH="$(readlink -f "$1")"; shift
[ -f "$PATCH" ] || { echo "brak łatki: $PATCH" >&2; exit 2; }
NAME="$(basename "$PATCH" .patch)"
WT="$ROOT/.wp/mut-$NAME-$$"

cleanup() {
  (cd "$WT" 2>/dev/null && tools/dev/up.sh test down >/dev/null 2>&1) || true
  git -C "$ROOT" worktree remove --force "$WT" >/dev/null 2>&1 || true
}
trap cleanup EXIT

git -C "$ROOT" worktree add --detach "$WT" HEAD >/dev/null || exit 2
cd "$WT"
git apply --check "$PATCH" || { echo "WYNIK NIEWAŻNY: łatka $NAME nie nakłada się na HEAD"; exit 2; }
eval "$(tools/dev/up.sh test env)"
tools/dev/up.sh test up mariadb-test fake-llm >/dev/null || { echo "WYNIK NIEWAŻNY: stos testowy nie wstał"; exit 2; }

run_tests() { mutation_run_tests "$@"; }

echo "--- bez mutacji (oczekiwane: zielone)"
run_tests "$@"; rc=$?
mutation_classify_no_mutation "$rc" || exit $?

git apply "$PATCH"
echo "--- z mutacją $NAME (oczekiwane: czerwone)"
run_tests "$@"; rc=$?
mutation_classify_mutation "$rc" "$NAME"
