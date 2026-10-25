#!/usr/bin/env bash
# Budżety rozmiaru obrazów (kontrakt WP E0-3 C2, krok "image-size" w C7).
# Metryka: suma rozmiarów warstw z `docker image history --human=false` (bajty nieskompresowane,
# MB = 1 000 000 B). `docker image inspect .Size` wypisany obok, informacyjnie — magazyn containerd
# w Dockerze 29 raportuje tam inną treść (C2). Sumy liczy python3 (bc nie ma w kontenerze agenta).
# Kod 1: przekroczony którykolwiek budżet albo brak obrazu.
set -euo pipefail
ROOT="$(git rev-parse --show-toplevel)"
# Tag obrazów per worktree (WP E4-H3, kontrakt C5): buduj i sprawdzaj ten sam tag co reszta biegu.
. "$ROOT/tools/dev/wd-version.sh"
wd_export_version "$ROOT"

# Obraz OCR nie ma usługi (do E1-3) — buduje go tylko ten skrypt (C1)
docker build --target runtime-ocr -t "wawelsky/backend-ocr:${WD_VERSION}" "$ROOT/backend"

# check_image <obraz> <budżet_MB|->  — wypisuje linię formatu C7
check_image() {
  local image="$1" budget="$2" layers inspect_size
  if ! layers="$(docker image history --human=false --format '{{.Size}}' "$image")"; then
    echo "image-size: brak obrazu $image" >&2
    return 1
  fi
  inspect_size="$(docker image inspect -f '{{.Size}}' "$image")"
  printf '%s\n' "$layers" | python3 -c '
import sys

image, budget, inspect_size = sys.argv[1], sys.argv[2], sys.argv[3]
mb = sum(int(line) for line in sys.stdin if line.strip()) / 1_000_000
insp = float(inspect_size) / 1_000_000
if budget == "-":
    print(f"{image} {mb:.1f} MB (budżet -, inspect .Size {insp:.1f} MB) OK")
    raise SystemExit(0)
ok = mb <= float(budget)
verdict = "OK" if ok else "PRZEKROCZONY"
print(f"{image} {mb:.1f} MB (budżet {budget} MB, inspect .Size {insp:.1f} MB) {verdict}")
raise SystemExit(0 if ok else 1)
' "$image" "$budget" "$inspect_size"
}

rc=0
check_image "wawelsky/backend:${WD_VERSION}" 450 || rc=1
check_image "wawelsky/backend-ocr:${WD_VERSION}" 700 || rc=1
check_image "wawelsky/web:${WD_VERSION}" 120 || rc=1
check_image "wawelsky/fake-llm:${WD_VERSION}" 220 || rc=1
check_image "wawelsky/mariadb:${WD_VERSION}" - || rc=1
exit "$rc"
