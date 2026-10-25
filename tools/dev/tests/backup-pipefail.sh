#!/usr/bin/env bash
# Test T5 (WP E4-H3, kontrakt C6): awaria lewej strony potoku w backup.sh/restore.sh daje rc != 0.
# (a) statycznie: oba potoki w `bash -c` poprzedzone `set -o pipefail`;
# (b) dynamicznie (gdy obraz mariadb dostępny): `bash -c 'set -o pipefail; false | cat'` → rc != 0,
#     inaczej SKIP.
# Użycie: bash tools/dev/tests/backup-pipefail.sh; rc 0 = OK/SKIP, rc 1 = błąd.
set -euo pipefail
ROOT="$(git rev-parse --show-toplevel)"; cd "$ROOT"
fail() { echo "backup-pipefail: $*" >&2; exit 1; }

# (a) Statycznie: oba potoki mają `set -o pipefail` wewnątrz `bash -c`.
grep -Eq "bash -c 'set -o pipefail; mariadb-dump .*\| zstd" scripts/backup.sh \
  || fail "(a) backup.sh: potok mariadb-dump | zstd bez 'set -o pipefail' w bash -c"
grep -Eq "bash -c 'set -o pipefail; zstd -dc \| mariadb" scripts/restore.sh \
  || fail "(a) restore.sh: potok zstd -dc | mariadb bez 'set -o pipefail' w bash -c"
echo "backup-pipefail: (a) statycznie OK"

# (b) Dynamicznie: pipefail odrzuca błąd lewej strony potoku w obrazie mariadb.
IMAGE="wawelsky/mariadb:${WD_VERSION:-latest}"
if docker image inspect "$IMAGE" >/dev/null 2>&1; then
  rc=0
  docker run --rm --entrypoint bash "$IMAGE" -c 'set -o pipefail; false | cat' >/dev/null 2>&1 || rc=$?
  [ "$rc" -ne 0 ] || fail "(b) bash -c 'set -o pipefail; false | cat' w $IMAGE zwróciło rc 0"
  echo "backup-pipefail: (b) pipefail w obrazie OK (rc=$rc)"
else
  echo "backup-pipefail: SKIP (b) — brak obrazu $IMAGE"
fi

echo "backup-pipefail: OK"
