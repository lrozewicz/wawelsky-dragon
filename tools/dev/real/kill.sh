#!/usr/bin/env bash
# Narzędzie odporności wyroczni "real" (WP E5-H5 §6/T3): kontrolowana awaria w trakcie parsowania.
#   kill.sh child  <projekt>  — zabija PID potomka konwersji w kontenerze workera (o największym VmRSS)
#   kill.sh worker <projekt>  — zabija cały kontener workera i podnosi go z powrotem
# Woła je frontend/e2e-real/real-resilience.spec.ts przez `execFileSync` (nigdy `pkill`/`killall`).
set -euo pipefail

MODE="${1:-}"
PROJ="${2:-}"

# Guard: ruszamy wyłącznie projekty stosu tymczasowego clean-install.sh (wd-ci-*).
case "$PROJ" in
  wd-ci-*) ;;
  *)
    echo "kill.sh: nazwa projektu musi pasować do wd-ci-* (dostałem '$PROJ')" >&2
    exit 2
    ;;
esac

ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"

# Kod diagnostyczny w kontenerze: buduje drzewo procesów z /proc (ppid z /proc/<pid>/stat,
# VmRSS z /proc/<pid>/status), wybiera potomka PID 1 dowolnej głębokości (poza samym PID 1)
# o największym VmRSS >= 100 MB i drukuje jego PID; brak kandydata — nic nie drukuje.
# Nazwa procesu w /proc/<pid>/stat może zawierać spacje i nawiasy, stąd ppid bierzemy po ostatnim ')'.
# Kod w apostrofach (bez pojedynczych cudzysłowów w środku) — `python3 -c "$CHILD_PROBE"`.
CHILD_PROBE='
import os

procs = {}
for entry in os.listdir("/proc"):
    if not entry.isdigit():
        continue
    pid = int(entry)
    try:
        with open("/proc/%d/stat" % pid) as fh:
            stat = fh.read()
        fields = stat[stat.rindex(")") + 2:].split()
        ppid = int(fields[1])
        rss = 0
        with open("/proc/%d/status" % pid) as fh:
            for line in fh:
                if line.startswith("VmRSS:"):
                    rss = int(line.split()[1])  # kB
                    break
    except (OSError, ValueError, IndexError):
        continue
    procs[pid] = (ppid, rss)

descendants = set()
stack = [1]
while stack:
    parent = stack.pop()
    for pid, (ppid, _rss) in procs.items():
        if ppid == parent and pid not in descendants:
            descendants.add(pid)
            stack.append(pid)

best = None
for pid in descendants:
    if pid == 1:
        continue
    rss = procs[pid][1]
    if rss >= 100 * 1024 and (best is None or rss > procs[best][1]):
        best = pid
if best is not None:
    print(best)
'

# cid kontenera worker w danym projekcie compose (bez pliku env — nazwę projektu znamy z WD_CI_PROJECT).
worker_cid() {
  docker compose -p "$1" ps -q worker 2>/dev/null
}

# child: do 180 s co 2 s szuka potomka >= 100 MB; znalazłszy, wysyła SIGKILL i melduje `killed pid=<n>`.
kill_child() {
  local proj="$1" cid pid deadline
  cid="$(worker_cid "$proj")"
  [ -n "$cid" ] || { echo "kill.sh: brak kontenera worker w projekcie $proj" >&2; exit 1; }

  pid=""
  deadline=$((SECONDS + 180))
  while [ -z "$pid" ]; do
    pid="$(docker exec "$cid" python3 -c "$CHILD_PROBE" 2>/dev/null || true)"
    [ -n "$pid" ] && break
    if [ "$SECONDS" -ge "$deadline" ]; then
      echo "kill.sh: brak potomka >= 100 MB w 180 s (projekt $proj)" >&2
      exit 1
    fi
    sleep 2
  done

  # Obraz backendu nie ma binarki /bin/kill (kill jest wyłącznie wbudowany w sh) — dlatego sygnał
  # wysyłamy przez `sh -c`, a PID przekazujemy jako argument (bez wstawiania do treści polecenia).
  docker exec "$cid" sh -c 'kill -9 "$1"' sh "$pid"
  echo "killed pid=$pid"
}

# worker: zabija kontener i przywraca go tą samą kompozycją, co stos (env + lista -f z clean-install.sh).
kill_worker() {
  local proj="$1" cid
  if [ -z "${WD_CI_COMPOSE_ENV:-}" ] || [ -z "${WD_CI_COMPOSE_FILES:-}" ]; then
    echo "kill.sh: tryb worker wymaga WD_CI_COMPOSE_ENV i WD_CI_COMPOSE_FILES" >&2
    exit 2
  fi

  cid="$(worker_cid "$proj")"
  [ -n "$cid" ] || { echo "kill.sh: brak kontenera worker w projekcie $proj" >&2; exit 1; }
  docker kill "$cid" >/dev/null

  # $WD_CI_COMPOSE_FILES celowo bez cudzysłowów — to lista flag `-f <plik>` rozdzielona spacjami.
  # shellcheck disable=SC2086
  docker compose --env-file "$WD_CI_COMPOSE_ENV" -p "$proj" $WD_CI_COMPOSE_FILES \
    --profile fake up -d --wait worker >/dev/null
  echo "worker restarted"
}

case "$MODE" in
  child) kill_child "$PROJ" ;;
  worker) kill_worker "$PROJ" ;;
  *)
    echo "kill.sh: użycie: kill.sh <child|worker> <projekt>" >&2
    exit 2
    ;;
esac
