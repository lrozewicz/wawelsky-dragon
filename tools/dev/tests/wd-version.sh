#!/usr/bin/env bash
# Test T4 (WP E4-H3, kontrakt C5): domyślny tag obrazów per worktree.
# Źródłuje tools/dev/wd-version.sh i sprawdza wd_default_version / wd_export_version.
# Użycie: bash tools/dev/tests/wd-version.sh; rc 0 = zielono.
set -euo pipefail
ROOT="$(git rev-parse --show-toplevel)"; cd "$ROOT"
fail() { echo "wd-version: $*" >&2; exit 1; }

# shellcheck source=/dev/null
. tools/dev/wd-version.sh

[ "$(wd_default_version /x/.wp/E4-H3)" = "wt-e4-h3" ] \
  || fail "wd_default_version /x/.wp/E4-H3 != wt-e4-h3: $(wd_default_version /x/.wp/E4-H3)"
[ "$(wd_default_version /x/wawelsky-dragon)" = "wt-wawelsky-dragon" ] \
  || fail "wd_default_version /x/wawelsky-dragon != wt-wawelsky-dragon: $(wd_default_version /x/wawelsky-dragon)"
[ "$(wd_default_version /x/Foo_Bar)" = "wt-foo-bar" ] \
  || fail "wd_default_version /x/Foo_Bar != wt-foo-bar: $(wd_default_version /x/Foo_Bar)"

# Jawne WD_VERSION ma pierwszeństwo i zostaje bez zmian.
WD_VERSION=foo
wd_export_version /x/.wp/E4-H3
[ "$WD_VERSION" = "foo" ] || fail "jawne WD_VERSION=foo zmienione na $WD_VERSION"

# Bez WD_VERSION funkcja ustawia tag z katalogu i eksportuje go.
unset WD_VERSION
wd_export_version /x/.wp/E4-H3
[ "$WD_VERSION" = "wt-e4-h3" ] || fail "bez WD_VERSION nie ustawiono wt-e4-h3 (jest ${WD_VERSION:-puste})"
[ "$(bash -c 'printf %s "$WD_VERSION"')" = "wt-e4-h3" ] || fail "WD_VERSION nie jest eksportowane"

echo "wd-version: OK"
