# Biblioteka wyroczni: kroki (wd_step) i werdykt (wd_red / wd_green).
# Źródłowana przez .claude/verify*.sh; sama źródłuje ensure-tools.sh ze swojego katalogu.
# Bez set -e i bez cd; exit tylko w funkcjach werdyktu (wd_red, wd_green).

# --- Nadzorca rc= (DEC-277, WP E5-H7d) --------------------------------------
# Każda wyrocznia najwyższego poziomu kończy log linią "rc=<kod>". Wypisuje ją proces
# nadrzędny (nadzorca), bo pułapki EXIT skryptów (compose_build, verify.sh) nadpisałyby
# pułapkę biblioteki. Nadzorca uruchamia ten sam skrypt ($0) jako dziecko z
# WD_VERIFY_WRAPPED=1, czeka na nie, przekazuje TERM/INT i kończy się kodem dziecka.
# Bieg zagnieżdżony (WD_VERIFY_NESTED niepuste) milczy. Funkcja kończy proces `exit`,
# więc proces nadzorcy nie wraca ze źródłowania.
wd_supervise() {
  local child rc=0
  local forced=""
  WD_VERIFY_WRAPPED=1 "${BASH:-bash}" "$0" "$@" &
  child=$!
  trap 'forced=143; kill -TERM "$child" 2>/dev/null' TERM
  trap 'forced=130; kill -TERM "$child" 2>/dev/null' INT
  while :; do
    wait "$child" && rc=0 || rc=$?
    kill -0 "$child" 2>/dev/null || break
  done
  trap - TERM INT
  if [ -n "$forced" ] && [ "$rc" -ge 128 ]; then rc=$forced; fi
  echo "rc=$rc"
  exit "$rc"
}
if [ -z "${WD_VERIFY_NESTED:-}" ]; then
  if [ -n "${WD_VERIFY_WRAPPED:-}" ]; then
    unset WD_VERIFY_WRAPPED
  else
    wd_supervise "$@"
  fi
fi

. "$(dirname "${BASH_SOURCE[0]}")/ensure-tools.sh"

# Tag obrazów per worktree (WP E4-H3, kontrakt C5): bez jawnego WD_VERSION eksportujemy tag
# z katalogu worktree, żeby równoległe biegi nie nadpisywały wawelsky/*:latest.
. "$(dirname "${BASH_SOURCE[0]}")/wd-version.sh"
wd_export_version "$(git rev-parse --show-toplevel)"

# Domyślna liczba workerów xdist — N zmierzone w WP E5-H7 (DEC-266, raport
# work/wp/E5-H7/reports/T1-measure.md): 8 = najszybsze N z zapasem do limitu połączeń
# MariaDB testowego (szczyt 93/200 przy 8 wobec 128/200 przy 12; N=12 szybsze o ~11%).
WD_PYTEST_WORKERS_DEFAULT=8

# wd_xdist_args — argumenty równoległości pytest (kontrakt E5-H7 C1).
# WD_PYTEST_WORKERS: liczba całkowita albo "auto"; 0/1 = bez xdist (brak argumentu).
# Wypisuje "-n <N>" na stdout i nic przy N<2; wołane jako `$(wd_xdist_args)`
# (bez cudzysłowów — zamierzony word-splitting). Wartość nierozpoznana → ostrzeżenie
# na stderr i bieg sekwencyjny (bezpieczny spadek, nigdy cicha równoległość).
wd_xdist_args() {
  local workers="${WD_PYTEST_WORKERS:-$WD_PYTEST_WORKERS_DEFAULT}"
  case "$workers" in
    auto) printf -- '-n auto\n' ;;
    0 | 1) ;;
    '' | *[!0-9]*)
      echo "WD_PYTEST_WORKERS: oczekiwano liczby całkowitej lub 'auto', jest '$workers' — bieg sekwencyjny" >&2
      ;;
    *) printf -- '-n %s\n' "$workers" ;;
  esac
}

# --- Znane czerwienie bazy (analiza 2026-10-09, team-leader.md §Start p.5) ---
# work/known-red.md (zapisuje TL przy pre-flight na wp/<id>): linie "- `<nazwa kroku>` — powód".
# Krok z listy, który padnie, nie czerwieni wyroczni — wypisuje "ZNANA CZERWIEŃ BAZY". Kroki, które
# przechodzą, przechodzą normalnie. merge-queue.sh odrzuca WP z niepustą listą.
wd_known_red() {  # wypisuje nazwy kroków, po jednej w linii
  local f
  f="$(git rev-parse --show-toplevel 2>/dev/null)/work/known-red.md"
  [ -f "$f" ] || return 0
  sed -n 's/^- `\([^`]*\)`.*/\1/p' "$f"
}
WD_KNOWN_RED_LIST="$(wd_known_red)"

# wd_step <nazwa> <komenda> [arg...] — wypisuje "--- <nazwa>", uruchamia komendę;
# niezerowy kod wyjścia komendy = czerwień z tą nazwą (chyba że krok jest na liście znanych czerwieni bazy).
wd_step() {
  local name="$1"
  shift
  echo "--- $name"
  if "$@"; then
    return 0
  fi
  if [ -n "$WD_KNOWN_RED_LIST" ] && printf '%s\n' "$WD_KNOWN_RED_LIST" | grep -qxF -- "$name"; then
    echo "ZNANA CZERWIEŃ BAZY: $name (work/known-red.md) — nie czerwieni wyroczni"
    return 0
  fi
  wd_red "$name"
}

# --- Pamięć zielonej wyroczni po drzewie (analiza 2026-10-09: ten sam HEAD sprawdzano 4–5 razy) ---
# Klucz = drzewo HEAD (tylko przy czystym drzewie roboczym, bez review/ i .task/) + skrót treści skryptu
# wyroczni, tej biblioteki i work/known-red.md. Pamięć leży we wspólnym katalogu .git (widzą ją wszystkie
# worktree), więc Programista, Reviewer, hook bramki DONE i TL nie powtarzają biegu dla tego samego drzewa.
# Wyłączenie: WD_VERIFY_NO_CACHE=1.
wd_cache_key() {  # <rodzaj> → klucz albo pusto (drzewo brudne / brak gita)
  local tree dirty sums
  tree="$(git rev-parse -q --verify 'HEAD^{tree}' 2>/dev/null)" || return 0
  dirty="$(git status --porcelain --untracked-files=all 2>/dev/null | grep -vE '^.. (review|\.task)/' || true)"
  [ -z "$dirty" ] || return 0
  sums="$(cat "$(readlink -f "$0")" "${BASH_SOURCE[0]}" "$(git rev-parse --show-toplevel)/work/known-red.md" 2>/dev/null | sha256sum | cut -c1-16)"
  printf '%s-%s-%s\n' "$1" "$tree" "$sums"
}
wd_cache_dir() { printf '%s/wd-verify-cache\n' "$(cd "$(git rev-parse --git-common-dir)" && pwd)"; }
# wd_cache_hit <rodzaj> — zielony bieg dla tego drzewa już był: wypisuje werdykt i kończy proces kodem 0.
wd_cache_hit() {
  [ "${WD_VERIFY_NO_CACHE:-0}" = 1 ] && return 0
  local key
  key="$(wd_cache_key "$1")"
  [ -n "$key" ] && [ -f "$(wd_cache_dir)/$key" ] || return 0
  echo "--- pamięć wyroczni: drzewo $(git rev-parse --short 'HEAD^{tree}') zielone $(cat "$(wd_cache_dir)/$key") — bez powtórki (WD_VERIFY_NO_CACHE=1 wymusza bieg)"
  wd_green
}
# wd_cache_store <rodzaj> — zapamiętuje zielony bieg (wołać tuż przed wd_green).
wd_cache_store() {
  local key
  key="$(wd_cache_key "$1")"
  [ -n "$key" ] || return 0
  mkdir -p "$(wd_cache_dir)" && date -Is >"$(wd_cache_dir)/$key"
}

# wd_red <nazwa> — werdykt czerwony; exit 1 kończy skrypt, bo wołana jest z głównej powłoki (nie z subshellu).
wd_red() {
  echo "WYROCZNIA CZERWONA - nie przeszło: $1"
  exit 1
}

# wd_green — werdykt zielony; dziecko uruchomione z WD_VERIFY_NESTED=1 milczy (werdykt wypisuje rodzic).
wd_green() {
  if [ -z "${WD_VERIFY_NESTED:-}" ]; then
    echo "WYROCZNIA ZIELONA"
  fi
  exit 0
}
