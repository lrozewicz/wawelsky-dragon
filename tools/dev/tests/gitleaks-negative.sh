#!/usr/bin/env bash
# Test negatywny gitleaks (WP E5-2b T1): skan historii MUSI wykryć fałszywy klucz (rc != 0),
# a czyste repo MUSI przejść (rc == 0). Repo tymczasowe w mktemp -d, sprzątane; bez commitów w repo projektu.
set -euo pipefail
ROOT="$(git rev-parse --show-toplevel)"; cd "$ROOT"
CONFIG="$ROOT/security/gitleaks.toml"
. tools/dev/ensure-tools.sh
ensure_gitleaks || { echo "gitleaks-negative: ensure_gitleaks nie powiodło się" >&2; exit 1; }

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
fail() { echo "gitleaks-negative: $*" >&2; exit 1; }

# Przypadek 1: repo z fałszywym GitHub PAT-em (format reguły github-pat) — oczekiwane wykrycie.
dirty="$tmp/dirty"
mkdir -p "$dirty"
git -C "$dirty" init -q
printf 'token = "ghp_aB3dE6gH9jK2mN5pQ8sT1vW4yZ7cF0hJ3kL6"\n' > "$dirty/leak.txt"
git -C "$dirty" add leak.txt
git -C "$dirty" -c user.name=test -c user.email=test@example.invalid commit -q -m leak
rc=0
gitleaks git --config "$CONFIG" --redact --no-banner --exit-code 1 "$dirty" >/dev/null 2>&1 || rc=$?
[ "$rc" -ne 0 ] || fail "fałszywy klucz nie został wykryty (rc=0)"

# Przypadek 2: czyste repo bez sekretów — skan musi przejść.
clean="$tmp/clean"
mkdir -p "$clean"
git -C "$clean" init -q
printf 'hello world\n' > "$clean/readme.txt"
git -C "$clean" add readme.txt
git -C "$clean" -c user.name=test -c user.email=test@example.invalid commit -q -m clean
rc=0
gitleaks git --config "$CONFIG" --redact --no-banner --exit-code 1 "$clean" >/dev/null 2>&1 || rc=$?
[ "$rc" -eq 0 ] || fail "czyste repo nie przeszło (rc=$rc)"

echo "gitleaks-negative: OK (fałszywy klucz wykryty, czyste repo przeszło)"
