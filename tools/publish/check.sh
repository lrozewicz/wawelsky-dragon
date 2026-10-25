#!/usr/bin/env bash
# Sprawdzian publikacji (WP E5-6, CONTRACT §C1/§C4; źródło wzorca: DEC-313).
# Eksportuje drzewo publikacji (przez `export.sh`) do katalogu tymczasowego i szuka wzorca
# zabronionego w treści plików ORAZ w ich ścieżkach (nazwach plików/katalogów).
# Wzorzec trzymamy poza drzewem publikacji (`private/publish/pattern.txt`), bo sam nazywa klienta;
# ścieżkę można nadpisać przez `WD_PUBLISH_PATTERN_FILE`.
# Kod wyjścia: 0 = brak trafień; 1 = trafienia (`plik:linia`, a dla trafień wyłącznie w nazwie —
# sama ścieżka) na stdout; 2 = brak albo pusty plik wzorca.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
ROOT="$(git rev-parse --show-toplevel)"

pattern_file="${WD_PUBLISH_PATTERN_FILE:-$ROOT/private/publish/pattern.txt}"
if [ ! -f "$pattern_file" ]; then
  echo "publish-check: brak pliku wzorca: $pattern_file" >&2
  exit 2
fi

# Pierwsza niepusta, niekomentarzowa linia (bez wiodących/końcowych białych znaków).
PATTERN=""
while IFS= read -r line; do
  line="${line%%#*}"
  line="${line#"${line%%[![:space:]]*}"}"
  line="${line%"${line##*[![:space:]]}"}"
  [ -n "$line" ] && { PATTERN="$line"; break; }
done < "$pattern_file"
if [ -z "$PATTERN" ]; then
  echo "publish-check: pusty wzorzec w $pattern_file" >&2
  exit 2
fi

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

"$SCRIPT_DIR/export.sh" "$tmp/tree"
tree="$tmp/tree"

found=0
while IFS= read -r -d '' path; do
  rel="${path#"$tree"/}"
  # Trafienie w ścieżce (nazwie pliku lub katalogu).
  if printf '%s' "$rel" | grep -qiE "$PATTERN"; then
    printf '%s\n' "$rel"
    found=1
  fi
  # Trafienia w treści — `plik:linia`.
  while IFS= read -r hit; do
    printf '%s\n' "$rel:${hit%%:*}"
    found=1
  done < <(grep -niE "$PATTERN" "$path" || true)
done < <(find "$tree" -type f -print0)

[ "$found" -eq 0 ] || exit 1
exit 0
