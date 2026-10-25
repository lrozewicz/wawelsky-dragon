#!/usr/bin/env bash
# Generuje plik sekretów WD_* z losowymi wartościami (kontrakt WP E0-3 C10).
# Treść = .env.example z korzenia repo z podmienionymi liniami sekretów; reszta bez zmian.
# Sekrety trafiają wyłącznie do pliku docelowego (nigdy na stdout/stderr).
set -euo pipefail
umask 077

usage() {
  echo "użycie: gen-secrets.sh [--force] [ŚCIEŻKA]" >&2
}

force=false
target=""
for arg in "$@"; do
  case "$arg" in
    --force)
      force=true
      ;;
    -*)
      usage
      exit 2
      ;;
    *)
      if [ -n "$target" ]; then
        usage
        exit 2
      fi
      target="$arg"
      ;;
  esac
done
target="${target:-.env}"

example="$(dirname "$(readlink -f "$0")")/../.env.example"

if [ -e "$target" ] && [ "$force" != true ]; then
  echo "plik $target istnieje — użyj --force" >&2
  exit 1
fi
if [ -e "$target" ]; then
  printf 'nadpisać %s? [t/N] ' "$target" >&2
  reply=""
  IFS= read -r reply
  if [ "$reply" != "t" ] && [ "$reply" != "T" ]; then
    exit 1
  fi
fi

export GEN_DB_PASSWORD="$(openssl rand -hex 24)"
export GEN_DB_ROOT_PASSWORD="$(openssl rand -hex 24)"
export GEN_SECRET_KEY="$(openssl rand -base64 48)"
export GEN_CRYPTO_KEY="$(openssl rand -hex 32)"
export GEN_HUB_COMPAT_API_SECRET="$(openssl rand -hex 32)"

target_dir="$(dirname "$target")"
tmp="$(mktemp "$target_dir/.gen-secrets.XXXXXX")"
trap 'rm -f "$tmp"' EXIT

awk '
  /^WD_DB_PASSWORD=/ { print "WD_DB_PASSWORD=" ENVIRON["GEN_DB_PASSWORD"]; next }
  /^WD_DB_ROOT_PASSWORD=/ { print "WD_DB_ROOT_PASSWORD=" ENVIRON["GEN_DB_ROOT_PASSWORD"]; next }
  /^WD_SECRET_KEY=/ { print "WD_SECRET_KEY=" ENVIRON["GEN_SECRET_KEY"]; next }
  /^WD_CRYPTO_KEY=/ { print "WD_CRYPTO_KEY=" ENVIRON["GEN_CRYPTO_KEY"]; next }
  /^WD_HUB_COMPAT_API_SECRET=/ { print "WD_HUB_COMPAT_API_SECRET=" ENVIRON["GEN_HUB_COMPAT_API_SECRET"]; next }
  { print }
' "$example" > "$tmp"

chmod 600 "$tmp"
mv -f "$tmp" "$target"
trap - EXIT

echo "wygenerowano $target"
