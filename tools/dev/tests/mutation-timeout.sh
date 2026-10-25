#!/usr/bin/env bash
# Test powłoki T2 (WP E5-H10): limit czasu uruchomień testów w tools/dev/mutation-check.sh.
# Logika limitów i klasyfikacji rc jest w tools/dev/mutation-lib.sh, więc test nie potrzebuje stosu docker:
# komendę testów wstrzykujemy przez WD_MUTATION_TEST_CMD, a limit skracamy przez WD_MUTATION_TIMEOUT_S.
# Użycie: bash tools/dev/tests/mutation-timeout.sh; rc 0 = zielono, rc 1 = błąd.
set -euo pipefail
ROOT="$(git rev-parse --show-toplevel)"; cd "$ROOT"
fail() { echo "mutation-timeout: $*" >&2; exit 1; }

# shellcheck source=/dev/null
. tools/dev/mutation-lib.sh

# (a) test dłuższy niż limit → run_tests zwraca 124, a klasyfikacja z mutacją: „MUTACJA: TIMEOUT”, rc 3.
rc=0
WD_MUTATION_TEST_CMD='sleep 5' WD_MUTATION_TIMEOUT_S=1 mutation_run_tests || rc=$?
[ "$rc" -eq 124 ] || fail "(a) run_tests pod limitem: rc=$rc zamiast 124 (timeout nie ubija testów)"

rc=0; out="$(mutation_classify_mutation 124 e5-h10-test.patch)" || rc=$?
[ "$rc" -eq 3 ] || fail "(a) klasyfikacja timeoutu z mutacją: rc=$rc zamiast 3"
[[ "$out" == *"MUTACJA: TIMEOUT"* ]] || fail "(a) brak komunikatu 'MUTACJA: TIMEOUT': $out"
case "$out" in
  *WYKRYTA*|*PRZEŻYŁA*) fail "(a) komunikat timeoutu myli się z WYKRYTA/PRZEŻYŁA: $out" ;;
esac

# (b) zachowanie istniejące: rc 1 z mutacją → „MUTACJA WYKRYTA”, rc 0.
rc=0; out="$(mutation_classify_mutation 1 e5-h10-test.patch)" || rc=$?
[ "$rc" -eq 0 ] || fail "(b) rc 1 z mutacją: rc=$rc zamiast 0"
[[ "$out" == *"MUTACJA WYKRYTA"* ]] || fail "(b) brak komunikatu 'MUTACJA WYKRYTA': $out"

# (c) zachowanie istniejące: rc 0 z mutacją → „MUTACJA PRZEŻYŁA”, rc 1.
rc=0; out="$(mutation_classify_mutation 0 e5-h10-test.patch)" || rc=$?
[ "$rc" -eq 1 ] || fail "(c) rc 0 z mutacją: rc=$rc zamiast 1"
[[ "$out" == *"MUTACJA PRZEŻYŁA"* ]] || fail "(c) brak komunikatu 'MUTACJA PRZEŻYŁA': $out"

# (d) faza bez mutacji: zielone rc 0 → kontynuacja (rc 0), timeout → „WYNIK NIEWAŻNY: TIMEOUT bez mutacji”, rc 2.
rc=0; mutation_classify_no_mutation 0 || rc=$?
[ "$rc" -eq 0 ] || fail "(d) rc 0 bez mutacji: rc=$rc zamiast 0"

rc=0; out="$(mutation_classify_no_mutation 124)" || rc=$?
[ "$rc" -eq 2 ] || fail "(d) timeout bez mutacji: rc=$rc zamiast 2"
[[ "$out" == *"WYNIK NIEWAŻNY: TIMEOUT bez mutacji"* ]] || fail "(d) komunikat: $out"

# (e) 137 (128+SIGKILL: `--kill-after` ubił drzewo ignorujące TERM) to też timeout, nie „wynik nieważny”.
rc=0; out="$(mutation_classify_mutation 137 e5-h10-test.patch)" || rc=$?
[ "$rc" -eq 3 ] || fail "(e) rc 137 z mutacją: rc=$rc zamiast 3"
[[ "$out" == *"MUTACJA: TIMEOUT"* ]] || fail "(e) brak komunikatu 'MUTACJA: TIMEOUT' dla rc 137: $out"

# (f) statycznie, na liniach KODU (nie komentarzach): mutation-check.sh źródłuje bibliotekę i przerywa
# skrypt po nieważnym wyniku bez mutacji, a biblioteka ubija drzewo procesów (`timeout --kill-after=10`).
grep -q -- 'timeout --kill-after=10' tools/dev/mutation-lib.sh \
  || fail "(f) mutation-lib.sh bez 'timeout --kill-after=10' (uv zostawiłby procesy po limicie)"
grep -q 'tools/dev/mutation-lib.sh"' tools/dev/mutation-check.sh \
  || fail "(f) mutation-check.sh nie źródłuje mutation-lib.sh"
grep -qF 'mutation_classify_no_mutation "$rc" || exit $?' tools/dev/mutation-check.sh \
  || fail "(f) mutation-check.sh nie kończy się po nieważnym wyniku bez mutacji"

echo "mutation-timeout: OK (timeout → MUTACJA: TIMEOUT rc 3; rc 1 → MUTACJA WYKRYTA rc 0)"