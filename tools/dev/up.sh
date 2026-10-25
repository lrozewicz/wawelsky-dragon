#!/usr/bin/env bash
# Izolowany stos per worktree (02-flow-agentow §7). Przetestowany w spike'u S0.8 (2 worktree równolegle,
# 2 sesje playwright-cli, brak kolizji).
#
#   tools/dev/up.sh [up|down|url] [--sso]              # stos dev (prod + dev overlay)
#   tools/dev/up.sh test env|up|down|seed [usługa...]  # izolowany stos testowy (docker-compose.test.yml)
#
# - COMPOSE_PROJECT_NAME=wd-<nazwa katalogu worktree> (dev) / wd-test-<slug>-<6hex md5 ścieżki> (test)
#   → osobne kontenery, sieci i wolumeny.
# - WEB_PORT z puli WD_PORT_BASE..+WD_PORT_SPAN (dom. 18100..18299): hash ścieżki worktree, przesunięcie przy kolizji
#   z portem zajętym przez działający kontener; zapamiętany w .task/stack.env (gitignored).
# - Tryb test: porty z puli 18400–18599 w blokach po 4 (DB, LLM, API, WEB); blok zajęty, jeśli którykolwiek
#   z jego portów publikuje działający kontener INNEGO projektu. Kontenery własnego projektu
#   (etykieta com.docker.compose.project=COMPOSE_PROJECT_NAME) są pomijane, żeby `env` po starcie stosu
#   wskazywał ten sam blok portów co przed startem. Gdy COMPOSE_PROJECT_NAME i 4×WD_TEST_*_PORT są już
#   w środowisku (np. po eval "$(tools/dev/up.sh test env)"), używa ich bez ponownego liczenia.
# - --sso: najpierw deploy/keycloak/up.sh (Keycloak testowy obok stosu, D11), potem nakładka docker-compose.sso.yml.
# - Z kontenera Packhorse stos jest widoczny pod http://host.docker.internal:<port> (WD_HOST=host.docker.internal).
# - Bez bind-mountów ścieżek z kontenera agenta: daemon Dockera działa na hoście i nie zna ścieżek /host/...
set -euo pipefail
ROOT="$(git rev-parse --show-toplevel)"; cd "$ROOT"
# Tag obrazów per worktree (WP E4-H3, kontrakt C5): jawne WD_VERSION ma pierwszeństwo.
. "$ROOT/tools/dev/wd-version.sh"
wd_export_version "$ROOT"
docker compose version >/dev/null 2>&1 || { echo "Brak wtyczki 'docker compose' (w kontenerze Packhorse trzeba ją doinstalować — patrz docs/03-spike-s0-wyniki.md)" >&2; exit 3; }

case "${1:-up}" in
  test)
    ACTION="${2:-}"
    case "$ACTION" in
      env|up|down|seed) shift 2 ;;
      *) echo "użycie: $0 test env|up|down|seed [usługa...]" >&2; exit 2 ;;
    esac
    [ -f docker-compose.test.yml ] || { echo "brak docker-compose.test.yml w $ROOT" >&2; exit 3; }
    if [ -n "${COMPOSE_PROJECT_NAME:-}" ] && [ -n "${WD_TEST_DB_PORT:-}" ] && [ -n "${WD_TEST_LLM_PORT:-}" ] \
       && [ -n "${WD_TEST_API_PORT:-}" ] && [ -n "${WD_TEST_WEB_PORT:-}" ]; then
      : # środowisko już ustawione (eval "$(tools/dev/up.sh test env)") — bez ponownego liczenia
    else
      HASH="$(printf '%s' "$ROOT" | md5sum | cut -c1-6)"
      SLUG="$(basename "$ROOT" | tr 'A-Z' 'a-z' | tr -c 'a-z0-9\n' '-')-${HASH}"
      export COMPOSE_PROJECT_NAME="wd-test-${SLUG}"
      OFF=$(( 0x${HASH} % 50 ))
      # Porty kontenerów własnego projektu pomijamy — inaczej `env` po `up` wybrałby inny blok (C8).
      USED="$(docker ps --format '{{.Label "com.docker.compose.project"}}|{{.Ports}}' | grep -vF "${COMPOSE_PROJECT_NAME}|" | cut -d'|' -f2- || true)"
      for ((i = 0; i < 50; i++)); do
        B=$(( (OFF + i) % 50 ))
        P=$(( 18400 + 4 * B ))
        grep -qE ":(${P}|$((P+1))|$((P+2))|$((P+3)))->" <<<"$USED" || break
      done
      export WD_TEST_DB_PORT="$P" WD_TEST_LLM_PORT="$((P+1))" WD_TEST_API_PORT="$((P+2))" WD_TEST_WEB_PORT="$((P+3))"
    fi
    case "$ACTION" in
      env)
        H="${WD_HOST:-host.docker.internal}"
        echo "export COMPOSE_PROJECT_NAME=$COMPOSE_PROJECT_NAME"
        echo "export WD_TEST_DB_PORT=$WD_TEST_DB_PORT"
        echo "export WD_TEST_LLM_PORT=$WD_TEST_LLM_PORT"
        echo "export WD_TEST_API_PORT=$WD_TEST_API_PORT"
        echo "export WD_TEST_WEB_PORT=$WD_TEST_WEB_PORT"
        echo "export WD_DB_HOST=$H"
        echo "export WD_DB_PORT=$WD_TEST_DB_PORT"
        echo "export WD_DB_USER=wawelsky"
        echo "export WD_DB_PASSWORD=wawelsky-test"
        echo "# tylko test, nie sekret — 64 znaki hex wymagane przez backend/app/core/config.py"
        echo "export WD_CRYPTO_KEY=0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
        echo "# tylko test, nie sekret — min. 32 bajty (SECRET_KEY_MIN_BYTES); podpisuje JWT i stan OIDC"
        echo "export WD_SECRET_KEY=wawelsky-test-secret-key-0123456789abcdef"
        echo "export WD_DB_NAME=wawelsky_test"
        echo "export WD_LLM_BASE_URL=http://$H:$WD_TEST_LLM_PORT/v1"
        ;;
      up)   docker compose -f docker-compose.test.yml up -d --wait --build "$@" >&2 ;;
      down) docker compose -f docker-compose.test.yml down -v --remove-orphans "$@" >&2 ;;
      seed)
        # Testowy reset stanu na DZIAŁAJĄCYM stosie (C7, K9): bez auth, ciało {} opcjonalne.
        H="${WD_HOST:-host.docker.internal}"
        TMP="$(mktemp)"; trap 'rm -f "$TMP"' EXIT
        CODE="$(curl -sS --max-time 30 -o "$TMP" -w '%{http_code}' -X POST \
          -H 'Content-Type: application/json' -d '{}' \
          "http://$H:$WD_TEST_API_PORT/api/wd/v1/test/reset")" || CODE="000"
        if [ "$CODE" != "200" ]; then
          echo "stos testowy nie działa (tools/dev/up.sh test up mariadb-test migrate api): HTTP $CODE" >&2
          cat "$TMP" >&2
          exit 1
        fi
        ADMIN_EMAIL="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["data"]["admin_email"])' "$TMP")"
        API_KEY="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["data"]["api_key"])' "$TMP")"
        echo "UI_URL=http://$H:$WD_TEST_WEB_PORT"
        echo "API_URL=http://$H:$WD_TEST_API_PORT"
        echo "ADMIN_EMAIL=$ADMIN_EMAIL"
        echo "ADMIN_PASSWORD=wd-test-admin-1"
        echo "API_KEY=$API_KEY"
        ;;
    esac
    ;;
  up|down|url)
    CMD="${1:-up}"; SSO=""; [ "${2:-}" = "--sso" ] && SSO=1
    SLUG="$(basename "$ROOT" | tr 'A-Z' 'a-z' | tr -c 'a-z0-9\n' '-')"
    export COMPOSE_PROJECT_NAME="wd-${SLUG}"
    BASE="${WD_PORT_BASE:-18100}"; SPAN="${WD_PORT_SPAN:-200}"
    STATE=".task/stack.env"
    FILES=(-f docker-compose.yml -f docker-compose.dev.yml); [ -n "$SSO" ] && FILES+=(-f docker-compose.sso.yml)
    compose() { docker compose "${FILES[@]}" "$@"; }
    case "$CMD" in
      up)
        if [ -f "$STATE" ]; then . "$STATE"; else
          OFF=$(( 0x$(printf '%s' "$ROOT" | md5sum | cut -c1-6) % SPAN ))
          USED="$(docker ps --format '{{.Ports}}' | grep -oE ':[0-9]+->' | tr -d ':>-' || true)"
          for ((i = 0; i < SPAN; i++)); do
            WEB_PORT=$(( BASE + (OFF + i) % SPAN ))
            grep -qx "$WEB_PORT" <<<"$USED" || break
          done
          mkdir -p .task; echo "WEB_PORT=$WEB_PORT" >"$STATE"
        fi
        export WEB_PORT WD_HTTP_PORT="$WEB_PORT"
        [ -n "$SSO" ] && deploy/keycloak/up.sh
        compose up -d --build --wait >&2
        echo "WEB_URL=http://${WD_HOST:-localhost}:$WEB_PORT" ;;
      down) [ -f "$STATE" ] && . "$STATE"; export WEB_PORT="${WEB_PORT:-0}" WD_HTTP_PORT="${WEB_PORT:-0}"; compose down -v --remove-orphans >&2; rm -f "$STATE" ;;
      url)  . "$STATE"; echo "WEB_URL=http://${WD_HOST:-localhost}:$WEB_PORT" ;;
      *) echo "użycie: $0 [up|down|url] [--sso]" >&2; exit 2 ;;
    esac
    ;;
  *) echo "użycie: $0 [up|down|url] [--sso] | test env|up|down|seed [usługa...]" >&2; exit 2 ;;
esac
