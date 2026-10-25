#!/usr/bin/env bash
# Próbkowanie pamięci kontenera `worker` stosu wd-ci-* (CONTRACT WP E5-H5 §1, T1).
# Uruchamiany w tle przez tools/dev/clean-install.sh (zmienna WD_CI_MEM_OUT); każda próbka to
# wiersz TSV `epoch_s<TAB>bajty_użyte` dopisywany do pliku z $2. Ubijany w trap EXIT clean-install.sh.
#   tools/dev/real/mem-sampler.sh <projekt> <plik_tsv>
set -euo pipefail

PROJ="${1:?mem-sampler: brak nazwy projektu}"
OUT="${2:?mem-sampler: brak pliku wyjściowego}"

case "$PROJ" in
  wd-ci-*) ;;
  *) echo "mem-sampler: projekt '$PROJ' nie pasuje do wd-ci-*" >&2; exit 2 ;;
esac

# $1 = licznik Dockera (np. "1.2GiB", "500MiB", "1.5kB") → bajty.
# KiB/MiB/GiB/TiB są binarne (1024), kB/MB/GB/TB dziesiętne (1000) — jak w `docker stats`.
to_bytes() {
  local v="$1" num unit
  num="${v%%[A-Za-z]*}"
  unit="${v#"$num"}"
  case "$unit" in
    B)   awk -v n="$num" 'BEGIN { printf "%d", n }' ;;
    KiB) awk -v n="$num" 'BEGIN { printf "%d", n * 1024 }' ;;
    MiB) awk -v n="$num" 'BEGIN { printf "%d", n * 1048576 }' ;;
    GiB) awk -v n="$num" 'BEGIN { printf "%d", n * 1073741824 }' ;;
    TiB) awk -v n="$num" 'BEGIN { printf "%d", n * 1099511627776 }' ;;
    kB)  awk -v n="$num" 'BEGIN { printf "%d", n * 1000 }' ;;
    MB)  awk -v n="$num" 'BEGIN { printf "%d", n * 1000000 }' ;;
    GB)  awk -v n="$num" 'BEGIN { printf "%d", n * 1000000000 }' ;;
    TB)  awk -v n="$num" 'BEGIN { printf "%d", n * 1000000000000 }' ;;
    *)   return 1 ;;
  esac
}

while true; do
  cid="$(docker compose -p "$PROJ" ps -q worker 2>/dev/null || true)"
  if [ -n "$cid" ]; then
    mem="$(docker stats --no-stream --format '{{.MemUsage}}' "$cid" 2>/dev/null || true)"
    used="${mem%%/*}"                       # "1.2GiB / 4GiB" → "1.2GiB "
    used="$(printf '%s' "$used" | tr -d '[:space:]')"
    if [[ "$used" =~ ^[0-9]+(\.[0-9]+)?(B|kB|MB|GB|TB|KiB|MiB|GiB|TiB)$ ]]; then
      printf '%s\t%s\n' "$(date +%s)" "$(to_bytes "$used")" >>"$OUT"
    fi
  fi
  sleep 2
done
