#!/usr/bin/env bash
# Harness e2e (kontrakt WP E3-2 T1): stawia izolowany stos testowy, uruchamia Playwright
# (Chromium, headless) na kontenerze `web` i ZAWSZE sprząta — także przy porażce i Ctrl-C.
# Uruchamiany przez `bun run e2e` (albo `bun run e2e:sso`); kod wyjścia = kod Playwrighta.
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"

if [ "${1:-}" = "--sso" ]; then
  # S6-01b nie ma nakładki compose — scenariusz SSO jest poza tym zadaniem (T5).
  if [ -f docker-compose.sso.yml ]; then
    echo "S6-01b: --sso nie jest obsługiwane przez harness e2e (patrz T5)" >&2
  else
    echo "S6-01b: tryb test nie obsługuje --sso (brak docker-compose.sso.yml)" >&2
  fi
  exit 3
fi

# Porty i nazwa projektu stosu testowego (blok 18400–18599, osobny na worktree).
set -a
. <("$ROOT/tools/dev/up.sh" test env)
set +a

# Sprzątanie stosu — także po nieudanym Playwrightcie i po Ctrl-C (trap EXIT biegnie zawsze).
# Ścieżki bezwzględne: trap biegnie już z katalogu `frontend`.
cleanup() { "$ROOT/tools/dev/up.sh" test down || true; }
trap cleanup EXIT

# Adres hosta stosu — ta sama reguła co `tools/dev/up.sh test env`: z kontenera agenta porty
# opublikowane na hoście są nieosiągalne pod `localhost` (DEC-054). Poza kontenerem: WD_HOST=localhost.
HOST="${WD_HOST:-host.docker.internal}"

"$ROOT/tools/dev/up.sh" test up mariadb-test migrate api web fake-llm worker

# `up.sh test up` czeka na healthchecki compose; dodatkowo upewniamy się, że API przyjmuje ruch.
ready=0
for _ in $(seq 1 120); do
  if curl -fsS -o /dev/null "http://${HOST}:${WD_TEST_API_PORT}/health/ready"; then
    ready=1
    break
  fi
  sleep 1
done
if [ "$ready" -ne 1 ]; then
  echo "api: /health/ready nie odpowiedział w 120 s (${HOST}:${WD_TEST_API_PORT})" >&2
  exit 1
fi

export WD_E2E_API_URL="http://${HOST}:${WD_TEST_API_PORT}"
export WD_E2E_WEB_URL="http://${HOST}:${WD_TEST_WEB_PORT}"

# Przeglądarka celuje w ten sam adres co procesy Node (seed, `request`). Cookie `wd_refresh` ma
# flagę `Secure` tylko w prod (`_cookie_secure`), a stos testowy działa z `WD_ENV=test`, więc po
# HTTP sesja przeżywa F5 bez obejścia `e2e.localhost` (K8, T-clean).
export WD_E2E_BASE_URL="$WD_E2E_WEB_URL"

# Kontener Packhorse ustawia PLAYWRIGHT_BROWSERS_PATH=/opt/ms-playwright (przeglądarki
# playwright-cli, katalog tylko do odczytu, bez Chromium 1243 wymaganego przez @playwright/test
# 1.63.0). Harness korzysta z cache użytkownika — instalacja: patrz e2e/README.md.
export PLAYWRIGHT_BROWSERS_PATH="${WD_E2E_BROWSERS_PATH:-$HOME/.cache/ms-playwright}"

cd "$ROOT/frontend"
# Argumenty po `--` trafiają wprost do Playwrighta (`bun run e2e -- e2e/s04-chunks.spec.ts`).
rc=0
bunx playwright test "$@" || rc=$?
# Flaki (zielone dopiero po ponowieniu) — do raportu TL i rejestru work/logs/flaky.log (analiza 2026-10-09).
RESULTS="$ROOT/frontend/test-results/e2e-results.json"
if [ -f "$RESULTS" ]; then
  jq -r '.. | objects | select(has("specs")) | .specs[] | select(any(.tests[]; .status == "flaky"))
         | "\(.file) :: \(.title)"' "$RESULTS" 2>/dev/null | sort -u | while read -r line; do
    echo "FLAKY (zielony po ponowieniu): $line"
    mkdir -p "$ROOT/work/logs" && echo "$(date -Is) $(git -C "$ROOT" rev-parse --short HEAD) $line" >>"$ROOT/work/logs/flaky.log"
  done
fi
exit "$rc"
