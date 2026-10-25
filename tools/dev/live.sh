#!/usr/bin/env bash
# Biegi na PRAWDZIWYM LLM (testy -m live, eval --llm live) z kluczami z `.env` — plik właściciela (10-testy §358, 02-flow §10).
#
#   tools/dev/live.sh check                  czy .env ma WD_LLM_BASE_URL i WD_LLM_API_KEY (tylko TAK/NIE, bez wartości)
#   tools/dev/live.sh pytest-live [<test>…]  cd backend && pytest -m live [identyfikatory testów z tests/live/]
#   tools/dev/live.sh eval <profil>          cd backend && python -m wdeval.run --llm live --profile <profil>
#   tools/dev/live.sh sharepoint-live [<test>…]  cd backend && pytest -m sharepoint_live [tests/live/sharepoint/…] (tenant testowy, DECISIONS Q4)
#
# Sędzia wdeval może mieć osobny endpoint: WD_JUDGE_BASE_URL / WD_JUDGE_API_KEY / WD_JUDGE_MODEL / WD_JUDGE_PROVIDER (DECISIONS Q2).
#
# Bezpieczeństwo:
# - `.env` jest ładowany WYŁĄCZNIE do środowiska uruchamianego procesu; skrypt nigdy nie wypisuje jego treści ani wartości.
# - Dozwolone są tylko komendy z listy wyżej — żadnego „uruchom cokolwiek”, więc nie da się nim zrobić `env`, `cat .env` itp.
# - Argumenty są walidowane (profil: [a-z0-9_-]; testy: ścieżki tests/live/… z opcjonalnym ::nazwa).
# - Zmienia go tylko właściciel (hook guard-writes blokuje Programistom Write/Edit tego pliku).
set -euo pipefail
ROOT="$(git rev-parse --show-toplevel)"                  # kod: bieżący checkout/worktree (np. .wp/<id>)
# .env zawsze z GŁÓWNEGO checkoutu — działa w każdym worktree bez kopii ani dowiązania sekretu (DECISIONS Q7)
ENV_FILE="$(dirname "$(git rev-parse --path-format=absolute --git-common-dir)")/.env"

read_env() {
  [ -f "$ENV_FILE" ] || { echo "live.sh: brak $ENV_FILE — właściciel musi go utworzyć (wzór: .env.example)" >&2; exit 3; }
  set -a
  # shellcheck disable=SC1090
  . "$ENV_FILE"
  set +a
}
load_env() {
  read_env
  [ -n "${WD_LLM_BASE_URL:-}" ] && [ -n "${WD_LLM_API_KEY:-}" ] \
    || { echo "live.sh: .env nie ustawia WD_LLM_BASE_URL albo WD_LLM_API_KEY" >&2; exit 3; }
}
load_env_sp() {
  read_env
  [ -n "${WD_SP_TEST_TENANT_ID:-}" ] && [ -n "${WD_SP_TEST_CLIENT_ID:-}" ] && [ -n "${WD_SP_TEST_CLIENT_SECRET:-}" ] \
    || { echo "live.sh: .env nie ustawia WD_SP_TEST_TENANT_ID/CLIENT_ID/CLIENT_SECRET" >&2; exit 3; }
}
yn() { [ -n "${!1:-}" ] && echo TAK || echo NIE; }

cmd="${1:-}"; shift || true
case "$cmd" in
  check)
    [ "$#" -eq 0 ] || { echo "live.sh check: bez argumentów" >&2; exit 2; }
    load_env
    echo "live.sh: .env OK (WD_LLM_BASE_URL i WD_LLM_API_KEY ustawione)"
    echo "live.sh: sędzia osobno (WD_JUDGE_BASE_URL/API_KEY/MODEL): $(yn WD_JUDGE_BASE_URL)/$(yn WD_JUDGE_API_KEY)/$(yn WD_JUDGE_MODEL)"
    echo "live.sh: SharePoint (WD_SP_TEST_TENANT_ID/CLIENT_ID/CLIENT_SECRET): $(yn WD_SP_TEST_TENANT_ID)/$(yn WD_SP_TEST_CLIENT_ID)/$(yn WD_SP_TEST_CLIENT_SECRET)" ;;
  pytest-live)
    for t in "$@"; do
      [[ "$t" =~ ^tests/live/[A-Za-z0-9_/.-]+\.py(::[A-Za-z0-9_\[\].-]+)?$ ]] \
        || { echo "live.sh pytest-live: niedozwolony argument: $t (tylko tests/live/…py[::test])" >&2; exit 2; }
    done
    load_env
    cd "$ROOT/backend"
    exec uv run --frozen pytest -q -m live -p no:cacheprovider "$@" ;;
  eval)
    [ "$#" -eq 1 ] && [[ "$1" =~ ^[a-z0-9_-]+$ ]] || { echo "live.sh eval: podaj jeden profil [a-z0-9_-]" >&2; exit 2; }
    load_env
    cd "$ROOT/backend"
    exec uv run --frozen python -m wdeval.run --llm live --profile "$1" ;;
  sharepoint-live)
    for t in "$@"; do
      [[ "$t" =~ ^tests/live/sharepoint/[A-Za-z0-9_/.-]+\.py(::[A-Za-z0-9_\[\].-]+)?$ ]] \
        || { echo "live.sh sharepoint-live: niedozwolony argument: $t (tylko tests/live/sharepoint/…py[::test])" >&2; exit 2; }
    done
    load_env_sp
    cd "$ROOT/backend"
    exec uv run --frozen pytest -q -m sharepoint_live -p no:cacheprovider "$@" ;;
  *)
    echo "użycie: tools/dev/live.sh check | pytest-live [tests/live/…] | eval <profil> | sharepoint-live [tests/live/sharepoint/…]" >&2; exit 2 ;;
esac
