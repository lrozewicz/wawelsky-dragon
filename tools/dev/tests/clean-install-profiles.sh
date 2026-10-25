#!/usr/bin/env bash
# Test zmiennej WD_CI_PROFILES z tools/dev/clean-install.sh (brief T8 WP E6-2) — bez Dockera,
# wzorzec: tools/dev/clean-install.cleanup.test.sh.
#   (a) statycznie: skrypt dokumentuje zmienną w nagłówku i ma pętlę dokładającą --profile
#       do tablicy COMPOSE;
#   (b) dynamicznie: blok profili WYCIĘTY sed-em z clean-install.sh uruchamiany w atrapie
#       (realny kod, nie przepisanka — mutacja w pętli ma być wykryta) — WD_CI_PROFILES=mcp,
#       mcp,dodatkowy daje COMPOSE z --profile mcp --profile dodatkowy (po --profile fake),
#       a pusta/brak zmiennej nie dodaje nic.
# Użycie: bash tools/dev/tests/clean-install-profiles.sh; rc 0 = zielono.
set -euo pipefail

ROOT_REPO="$(git rev-parse --show-toplevel)"
CLEAN_INSTALL="$ROOT_REPO/tools/dev/clean-install.sh"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
fail() { echo "clean-install-profiles: $*" >&2; exit 1; }

# --- (a) statycznie: dokumentacja w nagłówku i pętla profili w skrypcie ---
grep -q 'WD_CI_PROFILES' "$CLEAN_INSTALL" \
  || fail "clean-install.sh: brak zmiennej WD_CI_PROFILES"
grep -q '^PROFILES_LINE="\${WD_CI_PROFILES:-}"$' "$CLEAN_INSTALL" \
  || fail "clean-install.sh: brak PROFILES_LINE z WD_CI_PROFILES"
grep -q 'COMPOSE+=(--profile "$prof")' "$CLEAN_INSTALL" \
  || fail "clean-install.sh: profile nie dochodzą do tablicy COMPOSE przez --profile"

# --- (b) dynamicznie: wycięty blok profili w atrapie tablicy COMPOSE ---
BLOCK="$TMP/profiles-block.sh"
sed -n '/^PROFILES_LINE=/,/^done$/p' "$CLEAN_INSTALL" >"$BLOCK"
grep -q 'COMPOSE+=(--profile "$prof")' "$BLOCK" \
  || fail "wycięty blok niekompletny (sed od PROFILES_LINE= do done): $(cat "$BLOCK")"

# Wrapper: atrapa COMPOSE + REALNY wycięty blok + wydruk tablicy. Blok czyta WD_CI_PROFILES,
# więc wartość zadaną dopisujemy do wrapper jako eksport (pusta = zostaje otoczenie).
run_block() {
  local profiles="${1-}"
  local wrapper="$TMP/wrapper.sh"
  {
    echo 'COMPOSE=(compose --profile fake)'
    if [ -n "$profiles" ]; then
      echo "WD_CI_PROFILES='${profiles}'"
    fi
    cat "$BLOCK"
    echo 'printf "%s\n" "${COMPOSE[*]}"'
  } >"$wrapper"
  bash "$wrapper"
}

RESULT="$(run_block '')"
[ "$RESULT" = "compose --profile fake" ] || fail "(b) pusta lista: '$RESULT', oczekiwano bez zmian"

RESULT="$(run_block 'mcp')"
[ "$RESULT" = "compose --profile fake --profile mcp" ] \
  || fail "(b) WD_CI_PROFILES=mcp: '$RESULT', oczekiwano dopisane --profile mcp"

RESULT="$(run_block 'mcp,dodatkowy')"
[ "$RESULT" = "compose --profile fake --profile mcp --profile dodatkowy" ] \
  || fail "(b) WD_CI_PROFILES=mcp,dodatkowy: '$RESULT', oczekiwane oba profile po przecinku"

# Zmienna z otoczenia (wrapper bez dopisku czyta WD_CI_PROFILES z środowiska).
RESULT="$(WD_CI_PROFILES=mcp run_block '')"
[ "$RESULT" = "compose --profile fake --profile mcp" ] \
  || fail "(b) WD_CI_PROFILES ze środowiska: '$RESULT'"

echo "clean-install-profiles: OK (WD_CI_PROFILES → --profile X na COMPOSE; pusta = bez zmian)"
