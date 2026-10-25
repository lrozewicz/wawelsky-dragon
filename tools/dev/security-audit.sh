#!/usr/bin/env bash
# Skan bezpieczeństwa repo (WP E5-2b, H16). Podkomendy: `gitleaks`.
# `gitleaks` skanuje CAŁĄ historię osiągalną z HEAD z allowlistą ścieżek security/gitleaks.toml; kod gitleaks propaguje.
# Skanowanie jest lokalne — po instalacji narzędzia nie wymaga sieci.
set -euo pipefail
ROOT="$(git rev-parse --show-toplevel)"; cd "$ROOT"
# Tag obrazów per worktree (WP E4-H3, kontrakt C5): spójny tag, gdy skrypt woła Docker/compose.
. "$ROOT/tools/dev/wd-version.sh"
wd_export_version "$ROOT"
. tools/dev/ensure-tools.sh

case "${1:-}" in
  gitleaks)
    ensure_gitleaks || exit 1
    gitleaks git --config security/gitleaks.toml --redact --no-banner --exit-code 1 --log-opts="HEAD" .
    ;;
  *)
    echo "użycie: $0 gitleaks" >&2
    exit 2
    ;;
esac
