#!/usr/bin/env bash
# Krok wyroczni "clean-install" (K1 poprawka 2026-10-04 p. 1, K8 poprawka 2026-10-04 p. 3; WP E5-H1 T3).
# Stawia PRODUKCYJNY docker-compose.yml z nakładką fake-llm na izolowanym projekcie wd-ci-*, czeka na
# gotowość stosu i przechodzi scenariusz pierwszego użytkownika w prawdziwej przeglądarce
# (frontend/e2e-real, Playwright). Kod wyjścia = kod Playwrighta; stos nie wstał → ≠ 0.
# Sieć stosu nazywa się WD_NET_NAME=<projekt>-net (izolacja sieci między równoległymi stosami wd-ci-*).
#
# Bez `POST /api/wd/v1/test/reset`, bez WD_TEST_MODE, bez SQL — to ma być czysta instalacja.
#
# Zmienne sterujące (WP E5-H5 §1; wszystkie opcjonalne, bez nich zachowanie jak dotąd):
#   WD_CI_SPEC          nazwa specu w frontend/e2e-real/ (domyślnie clean-install.spec.ts)
#   WD_CI_DEFAULT_CHAT  wartość WD_LLM_DEFAULT_CHAT stosu (domyślnie fake-chat)
#   WD_CI_MEM_OUT       jeśli ustawione: próbkowanie pamięci workera do tego pliku TSV
#   WD_CI_TIMEOUT_S     twardy limit `playwright test` (domyślnie 1800)
#   WD_CI_PROFILES      dodatkowe profile compose po przecinku (T8 WP E6-2, np. `mcp`);
#                       puste = zachowanie bez zmian. kill.sh profili nie dostaje — podnosi
#                       wyłącznie `worker` (usługa poza profilem), więc `--profile fake` mu
#                       wystarcza.
#
#   tools/dev/clean-install.sh
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel)"; cd "$ROOT"

# Tag obrazów per worktree (kontrakt WP E4-H3 C5): te same obrazy co krok "compose build".
. "$ROOT/tools/dev/wd-version.sh"
wd_export_version "$ROOT"

docker compose version >/dev/null 2>&1 || {
  echo "clean-install: brak wtyczki 'docker compose' w PATH" >&2
  exit 3
}

# Zmienne, które niżej wpisujemy do pliku .env, muszą pochodzić z tego pliku — powłoka ma
# pierwszeństwo nad --env-file w interpolacji compose, a wcześniejsze kroki wyroczni (np. smoke
# sdk-0.24: `eval "$(up.sh test env)"`) zostawiają w środowisku WD_LLM_*/WD_ENV stosu testowego.
# Bez tego czysta instalacja wskazywałaby na inny stos. WD_VERSION zostaje (tag obrazów).
# WD_CI_* i WD_REAL_* NIE są czyszczone: WD_CI_* sterują tym skryptem (kontrakt §1), a WD_REAL_*
# przechodzą do specu bez zmian (kontrakt §2).
unset WD_ENV WD_HTTP_PORT WD_PUBLIC_BASE_URL WD_ADMIN_EMAIL WD_ADMIN_PASSWORD WD_NET_NAME \
  WD_LLM_BASE_URL WD_LLM_API_KEY WD_LLM_DEFAULT_CHAT WD_LLM_DEFAULT_EMBEDDING \
  WD_LLM_DEFAULT_RERANK WD_LLM_DEFAULT_VLM

# Izolowany projekt i port z puli 18400–18599 (blok 1 portu) — ta sama logika haszu ścieżki co
# tools/dev/up.sh test env (up.sh nie da się źródłować bez efektów ubocznych → duplikat kilku linii).
HASH="$(printf '%s' "$ROOT" | md5sum | cut -c1-6)"
SLUG="$(basename "$ROOT" | tr 'A-Z' 'a-z' | tr -c 'a-z0-9\n' '-')"
PROJ="wd-ci-${SLUG}-${HASH}"
ARTIFACTS_DIR="${WD_CI_ARTIFACTS_DIR:-$ROOT/test-results-real/clean-install-$PROJ}"

USED="$(docker ps --format '{{.Ports}}' | grep -oE ':[0-9]+->' | tr -d ':>-' || true)"
OFF=$(( 0x${HASH} % 200 ))
PORT=""
for ((i = 0; i < 200; i++)); do
  P=$(( 18400 + (OFF + i) % 200 ))
  if ! grep -qx "$P" <<<"$USED"; then PORT="$P"; break; fi
done
[ -n "$PORT" ] || { echo "clean-install: brak wolnego portu w puli 18400-18599" >&2; exit 3; }

HOST="${WD_HOST:-host.docker.internal}"
TMP="$(mktemp -d)"
COMPOSE=(docker compose --env-file "$TMP/.env" -p "$PROJ" \
  -f "$ROOT/docker-compose.yml" -f "$ROOT/tools/dev/clean-install/compose.fake-llm.yml" --profile fake)

# Profile dodatkowe (T8 WP E6-2): `--profile X` do tablicy COMPOSE, suma z `fake`; Word splitting
# po przecinku zamierzony (WD_CI_PROFILES to lista bez cudzysłowów, np. `mcp` albo `mcp,other`).
# WD_CI_COMPOSE_FILES (restart workera w kill.sh) zostaje bez profili — worker jest poza profilem.
PROFILES_LINE="${WD_CI_PROFILES:-}"
for prof in ${PROFILES_LINE//,/ }; do
  COMPOSE+=(--profile "$prof")
done

ADMIN_PASSWORD="$(openssl rand -hex 8)" # 16 znaków hex; nigdy nie trafia na stdout/stderr
ADMIN_EMAIL="admin@clean-install.test"

# PID próbnika pamięci (WD_CI_MEM_OUT); pusty = nie uruchomiono.
MEM_PID=""

# trap EXIT: sprząta WYŁĄCZNIE własny projekt wd-ci-* (guard na nazwie) i katalog tymczasowy,
# także przy porażce stosu i niezerowym kodzie Playwrighta (K8 poprawka p. 3).
cleanup() {
  local rc=$?
  trap - EXIT
  if [ -n "${MEM_PID:-}" ]; then
    kill "$MEM_PID" 2>/dev/null || true
  fi
  case "$PROJ" in
    wd-ci-*)
      # Artefakty diagnostyczne przy porażce (K1 poprawka 2026-10-05b p. 4): PRZED `down -v`
      # zbieramy logi/stan stosu; collect.sh jest best-effort i nie zmienia kodu wyjścia.
      if [ "$rc" -ne 0 ]; then
        bash "$ROOT/tools/dev/real/collect.sh" "$PROJ" "$ARTIFACTS_DIR" >&2 || true
        echo "clean-install: artefakty diagnostyczne: $ARTIFACTS_DIR" >&2
      fi
      "${COMPOSE[@]}" down -v --remove-orphans >/dev/null 2>&1 || true
      ;;
  esac
  rm -rf -- "$TMP"
  exit "$rc"
}
trap cleanup EXIT

# .env czystej instalacji: sekrety z gen-secrets.sh + dopiski wg K8 poprawka p. 3 (w kolejności
# po oryginalnych liniach → późniejsze wpisy wygrywają w pliku). Hasła nie logujemy.
"$ROOT/scripts/gen-secrets.sh" "$TMP/.env"
append_env() { printf '%s=%s\n' "$1" "$2" >>"$TMP/.env"; }
append_env WD_HTTP_PORT "$PORT"
append_env WD_PUBLIC_BASE_URL "http://${HOST}:${PORT}"
append_env WD_ADMIN_EMAIL "$ADMIN_EMAIL"
append_env WD_ADMIN_PASSWORD "$ADMIN_PASSWORD"
append_env WD_NET_NAME "${PROJ}-net"
append_env WD_LLM_BASE_URL "http://fake-llm:8090/v1"
append_env WD_LLM_API_KEY "fake"
append_env WD_LLM_DEFAULT_CHAT "${WD_CI_DEFAULT_CHAT:-fake-chat}"
append_env WD_LLM_DEFAULT_EMBEDDING "fake-embed-1024"
append_env WD_LLM_DEFAULT_RERANK ""
append_env WD_LLM_DEFAULT_VLM "fake-vision"
chmod 600 "$TMP/.env"

stage_start="$(date +%s)"
"${COMPOSE[@]}" up -d --build --wait
echo "[clean-install] stage=start-stosu seconds=$(( $(date +%s) - stage_start ))"

# Próbnik pamięci workera (kontrakt §1) — start dopiero po wstaniu stosu, ubijany w cleanup.
if [ -n "${WD_CI_MEM_OUT:-}" ]; then
  "$ROOT/tools/dev/real/mem-sampler.sh" "$PROJ" "$WD_CI_MEM_OUT" &
  MEM_PID=$!
fi

# Zmienne dla specu (Playwright czyta je przez process.env); hasła nie wypisujemy.
export WD_CI_BASE_URL="http://${HOST}:${PORT}"
export WD_CI_ADMIN_EMAIL="$ADMIN_EMAIL"
export WD_CI_ADMIN_PASSWORD="$ADMIN_PASSWORD"
export WD_CI_SPEC="${WD_CI_SPEC:-clean-install.spec.ts}"
# Zmienne dla speców złożonych (T3: kill.sh stawia kontener z powrotem znając projekt i pliki compose).
export WD_CI_PROJECT="$PROJ"
export WD_CI_COMPOSE_ENV="$TMP/.env"
export WD_CI_COMPOSE_FILES="-f $ROOT/docker-compose.yml -f $ROOT/tools/dev/clean-install/compose.fake-llm.yml"
# Przeglądarka z cache użytkownika (jak frontend/e2e/README.md; kontener Packhorse ustawia
# PLAYWRIGHT_BROWSERS_PATH na katalog bez wymaganej wersji Chromium).
export PLAYWRIGHT_BROWSERS_PATH="${WD_E2E_BROWSERS_PATH:-$HOME/.cache/ms-playwright}"

# Bun w wersji wyroczni (ensure-tools.sh) — harness e2e-real odpalamy tym samym `bunx playwright`.
. "$ROOT/tools/dev/ensure-tools.sh"
ensure_bun || exit 1

rc=0
stage_start="$(date +%s)"
( cd "$ROOT/frontend" \
  && timeout "${WD_CI_TIMEOUT_S:-1800}" bunx playwright test -c e2e-real/playwright.config.ts ) || rc=$?
echo "[clean-install] stage=playwright seconds=$(( $(date +%s) - stage_start ))"
exit "$rc"
