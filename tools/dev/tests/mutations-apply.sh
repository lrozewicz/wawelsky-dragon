#!/usr/bin/env bash
# Strażnik łatek mutacyjnych (WP E7-H1, zadanie T1).
# Powód: `k19-import-owner.patch` przestała się nakładać po E7-1z i nikt tego nie zauważył
# do odbioru E7-2 — łatka mutacyjna, która nie nakłada się na HEAD, po cichu przestaje
# pilnować swojego testu (`tools/dev/mutation-check.sh` zwraca wtedy „WYNIK NIEWAŻNY”).
# Sprawdzian: dla każdej `backend/tests/mutations/*.patch` — `git apply --check` z korzenia repo.
# Bez Dockera i sieci (wzór: `tools/dev/tests/mutation-timeout.sh`).
# Katalog łatek wolno podać przez WD_MUTATIONS_DIR (test negatywny; wzór: WD_PUBLISH_PATTERN_FILE).
# Kod wyjścia: 0 = wszystkie łatki się nakładają; 1 = co najmniej jedna nie; 2 = błąd środowiska.
set -uo pipefail

ROOT="$(git rev-parse --show-toplevel)" || { echo "mutations-apply: nie jestem w repozytorium git" >&2; exit 2; }
DIR="${WD_MUTATIONS_DIR:-$ROOT/backend/tests/mutations}"

[ -d "$DIR" ] || { echo "mutations-apply: brak katalogu łatek: $DIR" >&2; exit 2; }

applied=0
failed=0
for patch in "$DIR"/*.patch; do
  [ -e "$patch" ] || continue
  applied=$((applied + 1))
  out="$(git -C "$ROOT" apply --check -- "$patch" 2>&1)" || {
    failed=$((failed + 1))
    echo "mutations-apply: NIE NAKŁADA SIĘ: $(basename "$patch")"
    printf '%s\n' "$out" | sed '/^$/d; s/^/    /'
  }
done

if [ "$applied" -eq 0 ]; then
  echo "mutations-apply: brak łatek w $DIR" >&2
  exit 2
fi

if [ "$failed" -gt 0 ]; then
  echo "mutations-apply: $failed z $applied łatek nie nakłada się na HEAD — napraw łatkę albo test, którego pilnuje" >&2
  exit 1
fi

echo "mutations-apply: $applied łatek OK"
