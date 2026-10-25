# Logika limitów czasu i klasyfikacji wyników mutacji — wydzielona z tools/dev/mutation-check.sh,
# żeby dała się przetestować bez stosu docker (tools/dev/tests/mutation-timeout.sh).
# Plik jest źródłowany — bez set -e, bez exit, bez cd; komunikaty na stdout, wynik przez return.

# Uruchamia testy pod limitem czasu WD_MUTATION_TIMEOUT_S (domyślnie 900 s).
# `--kill-after=10` ubija też procesy potomne — samo TERM nie kończy `uv run`.
# WD_MUTATION_TEST_CMD nadpisuje komendę testów (używane w teście powłoki, bez dockera).
mutation_run_tests() {
  if [ -n "${WD_MUTATION_TEST_CMD:-}" ]; then
    timeout --kill-after=10 "${WD_MUTATION_TIMEOUT_S:-900}" bash -c "$WD_MUTATION_TEST_CMD"
  else
    (cd backend && timeout --kill-after=10 "${WD_MUTATION_TIMEOUT_S:-900}" \
      uv run --frozen pytest -q -p no:cacheprovider "$@")
  fi
}

# Faza bez mutacji. rc: 0 — testy zielone (idź dalej), 2 — wynik nieważny (TIMEOUT lub czerwień).
# 137 = 128+SIGKILL: `timeout --kill-after` musiał ubić drzewo, które zignorowało TERM — to też timeout.
mutation_classify_no_mutation() {
  case "$1" in
    0) return 0 ;;
    124|137) echo "WYNIK NIEWAŻNY: TIMEOUT bez mutacji"; return 2 ;;
    *) echo "WYNIK NIEWAŻNY: testy czerwone już bez mutacji (kod $1)"; return 2 ;;
  esac
}

# Faza z mutacją. rc: 0 — wykryta, 1 — przeżyła, 2 — wynik nieważny, 3 — TIMEOUT (limit czasu).
mutation_classify_mutation() {
  case "$1" in
    1) echo "MUTACJA WYKRYTA: ${2:-mutacja} — testy czerwone"; return 0 ;;
    0) echo "MUTACJA PRZEŻYŁA: ${2:-mutacja} — testy zielone mimo błędu"; return 1 ;;
    124|137) echo "MUTACJA: TIMEOUT — testy nie zakończyły się w limicie czasu"; return 3 ;;
    *) echo "WYNIK NIEWAŻNY: pytest z mutacją zakończył się kodem $1"; return 2 ;;
  esac
}