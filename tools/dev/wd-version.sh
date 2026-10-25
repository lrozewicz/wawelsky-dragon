# Tag obrazów per worktree (WP E4-H3, kontrakt C5). Plik źródłowany — bez set -e, bez cd, bez exit.
# Bez jawnego WD_VERSION wyrocznia i stosy testowe używają tagu z nazwy katalogu worktree,
# żeby równoległe biegi w różnych worktree nie nadpisywały wawelsky/*:latest.

wd_default_version() {  # $1 = korzeń worktree; wypisuje tag
  printf 'wt-%s' "$(basename "$1" | tr 'A-Z' 'a-z' | tr -c 'a-z0-9.\n-' '-')"
}

wd_export_version() {  # $1 = korzeń; jawne WD_VERSION ma pierwszeństwo
  [ -n "${WD_VERSION:-}" ] || WD_VERSION="$(wd_default_version "$1")"
  export WD_VERSION
}
