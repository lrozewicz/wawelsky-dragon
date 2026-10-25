#!/usr/bin/env bash
# Eksport drzewa publikacji (WP E5-6, DEC-311 §C4).
# Kopiuje pliki śledzone przez git (`git ls-files`, stan drzewa roboczego) minus wzorce ścieżek
# z `tools/publish/exclude.txt`. Pomija pliki śledzone, lecz nieobecne na dysku.
# Bez zależności od `rsync` — używa `cp --parents`.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
EXCLUDE="$SCRIPT_DIR/exclude.txt"
ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"

target="${1:-}"
if [ -z "$target" ]; then
  echo "użycie: $(basename "$0") <katalog-docelowy>" >&2
  exit 2
fi
mkdir -p "$target"
target="$(cd "$target" && pwd)"

# Odczyt wzorców: obcinamy komentarze (`#`), usuwamy wiodące/końcowe białe znaki, pomijamy puste.
patterns=()
while IFS= read -r line; do
  line="${line%%#*}"
  line="${line#"${line%%[![:space:]]*}"}"
  line="${line%"${line##*[![:space:]]}"}"
  [ -n "$line" ] && patterns+=("$line")
done < "$EXCLUDE"

# Wzorzec zakończony `/` = prefiks katalogu; pozostałe = dokładna ścieżka pliku.
is_excluded() {
  local path="$1" pat
  for pat in "${patterns[@]}"; do
    if [ "${pat%/}" = "$pat" ]; then
      [ "$path" = "$pat" ] && return 0
    else
      case "$path" in "$pat"*) return 0 ;; esac
    fi
  done
  return 1
}

while IFS= read -r path; do
  [ -n "$path" ] || continue
  [ -f "$path" ] || continue
  is_excluded "$path" && continue
  cp --parents -p "$path" "$target"
done < <(git ls-files)
