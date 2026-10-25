#!/usr/bin/env bash
# Test negatywny wzorca publikacji (WP E5-H10 T4, DEC-330).
# Sprawdzian `tools/publish/check.sh` MUSI wykryć każdą formę odmienioną nazwy klienta w treści
# pliku drzewa publikacji (formy w `private/publish/forms.txt` — plik niepublikowany, bo nazywa
# klienta, DEC-313), także gdy forma jest sklejona znakiem niealfanumerycznym (identyfikator
# `wd_<forma>_x`), a wyrazy brzmiące jedynie podobnie NIE mogą dawać trafień.
# Mini-repo w `mktemp -d`, sprzątane; bez commitów w repo projektu (wzór: `tools/dev/tests/gitleaks-negative.sh`).
# Kod wyjścia: 0 = wszystkie przypadki zgodne z oczekiwaniem; 1 = niezgodność; 2 = brak danych wejściowych.
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel)"; cd "$ROOT"
PATTERN_FILE="${WD_PUBLISH_PATTERN_FILE:-$ROOT/private/publish/pattern.txt}"
FORMS_FILE="${WD_PUBLISH_FORMS_FILE:-$ROOT/private/publish/forms.txt}"

bad_input() { echo "check-negative: $*" >&2; exit 2; }
fail() { echo "check-negative: $*" >&2; exit 1; }

[ -f "$PATTERN_FILE" ] || bad_input "brak pliku wzorca: $PATTERN_FILE"
[ -f "$FORMS_FILE" ] || bad_input "brak pliku form nazwy: $FORMS_FILE"

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

# Buduje mini-repo (plik trafia do indeksu git) i uruchamia realny sprawdzian na jego drzewie publikacji.
run_case() { # <nazwa przypadku> <treść pliku> → kod wyjścia sprawdzianu
  local name="$1" text="$2" rc=0
  local dir="$tmp/$name"
  mkdir -p "$dir/docs"
  git -C "$dir" init -q
  printf '%s\n' "$text" > "$dir/docs/note.md"
  git -C "$dir" add -A
  ( cd "$dir" && WD_PUBLISH_PATTERN_FILE="$PATTERN_FILE" bash "$ROOT/tools/publish/check.sh" ) \
    > "$tmp/$name.out" 2>&1 || rc=$?
  printf '%s' "$rc"
}

# Oczekiwania. Liczniki są globalne — funkcje wołamy bez podpowłoki.
hits=0
expect_hit() { # <treść> <opis> — sprawdzian MUSI dać rc 1
  local case_name="hit-$hits" rc
  rc="$(run_case "$case_name" "$1")"
  [ "$rc" = 1 ] || fail "nie wykryto: $2 (rc=$rc; $(tr '\n' ' ' < "$tmp/$case_name.out"))"
  hits=$((hits + 1))
  echo "OK: $2 → rc 1 ($(head -n1 "$tmp/$case_name.out"))"
}

cleans=0
expect_clean() { # <treść> <opis> — sprawdzian MUSI dać rc 0
  local case_name="clean-$cleans" rc
  rc="$(run_case "$case_name" "$1")"
  [ "$rc" = 0 ] || fail "fałszywe trafienie: $2 (rc=$rc; $(tr '\n' ' ' < "$tmp/$case_name.out"))"
  cleans=$((cleans + 1))
  echo "OK: $2 → rc 0"
}

# 1) Każda forma odmieniona nazwy (mianownik, dopełniacz, miejscownik, …) → trafienie (rc 1),
#    samodzielnie ORAZ sklejona podkreśleniem (granica lewa nie może wymagać litery przed rdzeniem —
#    stary wzorzec łapał identyfikatory, a `\b` by je przepuścił; DEC-330).
#    `|| [ -n "$form" ]` — ostatnia linia bez znaku nowej linii też ma być sprawdzona (inaczej cicho wypada).
while IFS= read -r form || [ -n "$form" ]; do
  case "$form" in ''|'#'*) continue ;; esac
  expect_hit "wpis testowy: $form" "forma '$form'"
  expect_hit "wpis testowy: wd_${form}_x" "forma '$form' w identyfikatorze"
done < "$FORMS_FILE"
[ "$hits" -gt 0 ] || bad_input "brak form w $FORMS_FILE"

# 2) Wyrazy podobne, ale nie będące nazwą jako całym słowem (nazwa zakładu opieki, dzielnica) → rc 0.
#    Te dwa wolno wpisać w tym pliku: nie zawierają nazwy klienta jako całości, więc sam sprawdzian ich nie łapie.
for word in agorafobia Zagorze; do
  expect_clean "wyraz bez nazwy: $word" "wyraz '$word'"
done

echo "check-negative: OK ($hits przypadków trafień wykrytych, $cleans wyrazy podobne bez trafień)"