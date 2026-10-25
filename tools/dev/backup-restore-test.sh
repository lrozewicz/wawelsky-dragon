#!/usr/bin/env bash
# Test odtworzenia B1 (kontrakt WP E5-3 C5): backup → `down -v` → świeży stos → restore →
# liczniki i sekrety odtworzone, blob dokumentu zgodny, rotacja WD_CRYPTO_KEY bezpieczna.
# Stawia WŁASNY izolowany stos testowy (wd-test-<slug>) i zawsze go zdejmuje (trap: `up.sh test
# down`, czyli `down -v` wyłącznie własnego projektu + rm katalogu tymczasowego z kopią).
#
# Hak testowy (jedyny, poza normą): BRT_SABOTAGE=1 — po restore, a przed porównaniem liczników,
# usuwa jeden wiersz z `chunks`, żeby potwierdzić, że porównanie realnie wykrywa różnicę (kod 1).
#
# Nigdy nie wypisujemy kluczy ani haseł; nowy klucz żyje tylko w zmiennej i w pliku override
# w katalogu tymczasowym (chmod 600, usuwany w trap). Bez `set -x`.
set -euo pipefail
ROOT="$(git rev-parse --show-toplevel)"; cd "$ROOT"
# Tag obrazów per worktree (WP E4-H3, kontrakt C5): ten sam tag co build stosu testowego.
. "$ROOT/tools/dev/wd-version.sh"
wd_export_version "$ROOT"
UP="$ROOT/tools/dev/up.sh"
COMPOSE_FILE="$ROOT/docker-compose.test.yml"
TMP=""
cleanup() {
  "$UP" test down >/dev/null 2>&1 || true
  if [ -n "$TMP" ]; then rm -rf "$TMP"; fi
}
trap cleanup EXIT
fail() { echo "backup-restore-test: $*" >&2; exit 1; }

wait_api_ready() { # gotowość api po restarcie: pętla ≤120 s na /health/ready (nie sam kontener)
  local deadline=$((SECONDS + 120))
  while [ "$SECONDS" -lt "$deadline" ]; do
    if curl -sf --max-time 5 "$API_URL/health/ready" >/dev/null 2>&1; then return 0; fi
    sleep 1
  done
  echo "backup-restore-test: ostatnie 20 linii logów api:" >&2
  "${COMPOSE[@]}" logs --tail 20 api >&2 || true
  fail "api nie jest gotowe po 120 s"
}

# Tabele liczników (nazwy z DDL alembic 0001..0006): ≥ 8 pozycji, czaty i sesje osobno.
TABLES=(users datasets documents chunks chats chat_sessions models provider_instances integrations api_keys)

eval "$("$UP" test env)"
# API_URL znane już po `test env` (deterministyczne z portu bloku) — potrzebne, by czekać na
# gotowość api jeszcze przed `seed` (up.sh test seed sam wymaga działającego API).
API_URL="http://${WD_HOST:-host.docker.internal}:$WD_TEST_API_PORT"
COMPOSE=(docker compose -f "$COMPOSE_FILE" -p "$COMPOSE_PROJECT_NAME")
TMP="$(mktemp -d)"

api() { # api METHOD PATH [JSON] — ciało na stdout (nagłówek z tokenem)
  local method="$1" path="$2" data="${3:-}"
  if [ -n "$data" ]; then
    curl -sS --max-time 60 -X "$method" -H "Authorization: Bearer $TOKEN" \
      -H 'Content-Type: application/json' -d "$data" "$API_URL$path"
  else
    curl -sS --max-time 60 -X "$method" -H "Authorization: Bearer $TOKEN" "$API_URL$path"
  fi
}

http_code() { # http_code METHOD PATH [JSON] — kod HTTP na stdout, ciało w $TMP/last.json
  local method="$1" path="$2" data="${3:-}"
  if [ -n "$data" ]; then
    curl -sS --max-time 60 -o "$TMP/last.json" -w '%{http_code}' -X "$method" \
      -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
      -d "$data" "$API_URL$path"
  else
    curl -sS --max-time 60 -o "$TMP/last.json" -w '%{http_code}' -X "$method" \
      -H "Authorization: Bearer $TOKEN" "$API_URL$path"
  fi
}

diagnose_post_restore_login_failure() { # T6: dowody przy porażce login PO restore
  local users emails cid_now img_now counts
  users="$(count_table users 2>/dev/null || echo '?')"
  counts="models=$(count_table models 2>/dev/null || echo '?'), api_keys=$(count_table api_keys 2>/dev/null || echo '?'), datasets=$(count_table datasets 2>/dev/null || echo '?'), alembic=$(count_table alembic_version 2>/dev/null || echo '?')"
  emails="$("${COMPOSE[@]}" exec -T mariadb-test sh -c \
    'mariadb -N -B -uroot -p"$MARIADB_ROOT_PASSWORD" "$MARIADB_DATABASE" -e "SELECT email FROM users"' \
    2>/dev/null || echo '?')"
  cid_now="$("${COMPOSE[@]}" ps -q mariadb-test 2>/dev/null || true)"
  img_now="$(docker inspect --format '{{.Image}}' "$cid_now" 2>/dev/null || echo '?')"
  {
    echo "backup-restore-test: DIAGNOSTYKA po restore:"
    echo "  users=$users"
    echo "  e-maile w users: ${emails//$'\n'/ }"
    echo "  liczniki: $counts (wyczyszczona baza = same 0 oprócz alembic)"
    echo "  mariadb-test: cid ${MARIADB_CID_PRE_RESTORE:-?} (przed restore) -> ${cid_now:-?} (teraz), obraz ${MARIADB_IMG_PRE_RESTORE:-?} -> ${img_now:-?}"
    echo "  dump=${DUMP_BYTES:-?}B/${DUMP_SQL_BYTES:-?}B, users_przed=$(value_of users "$TMP/before.txt" 2>/dev/null || echo '?')"
    echo "  ostatnie 15 linii $TMP/restore.out:"
    tail -n 15 "$TMP/restore.out" 2>/dev/null || true
    echo "  ostatnie 30 linii logów api:"
    "${COMPOSE[@]}" logs --tail 30 api 2>&1 || true
  } >&2
}

login() { # logowanie adminem z seedu; hasło nigdy nie trafia do logu; do 5 prób co 2 s
  local attempt code
  for attempt in 1 2 3 4 5; do
    code="$(curl -sS --max-time 30 -o "$TMP/login.json" -w '%{http_code}' -X POST \
      -H 'Content-Type: application/json' \
      -d "$(jq -nc --arg e "$ADMIN_EMAIL" --arg p "$ADMIN_PASSWORD" '{email:$e,password:$p}')" \
      "$API_URL/api/v1/auth/login")" || code="000"
    TOKEN="$(jq -r 'if .code == 0 then .data.access_token else empty end' "$TMP/login.json" 2>/dev/null || true)"
    if [ -n "$TOKEN" ]; then return 0; fi
    echo "login: próba $attempt/5 nieudana (HTTP $code): $(jq -c '{code,message}' "$TMP/login.json" 2>/dev/null || echo '{}')" >&2
    if [ "$attempt" -lt 5 ]; then sleep 2; fi
  done
  if [ "${POST_RESTORE:-0}" = "1" ]; then diagnose_post_restore_login_failure; fi
  fail "login: nie powiódł się po 5 próbach (HTTP $code)"
}

restore_diagnostics() { # T6: dowody, gdy restore.sh padnie (migrate/api/baza)
  {
    echo "backup-restore-test: DIAGNOSTYKA nieudanego restore:"
    echo "  ogon $TMP/restore.out:"
    tail -n 20 "$TMP/restore.out" 2>/dev/null || true
    echo "  migrate (ostatnie 60 linii):"
    "${COMPOSE[@]}" logs --tail 60 migrate 2>&1 || true
    echo "  mariadb-test (ostatnie 30 linii):"
    "${COMPOSE[@]}" logs --tail 30 mariadb-test 2>&1 || true
    echo "  users=$(count_table users 2>/dev/null || echo '?'), cid bazy=$("${COMPOSE[@]}" ps -q mariadb-test 2>/dev/null || echo '?')"
  } >&2
}

count_table() {
  "${COMPOSE[@]}" exec -T mariadb-test sh -c \
    'mariadb -N -B -uroot -p"$MARIADB_ROOT_PASSWORD" "$MARIADB_DATABASE" -e "SELECT COUNT(*) FROM '"$1"'"' \
    | tr -d '\r\n'
}

count_nonnull() {
  "${COMPOSE[@]}" exec -T mariadb-test sh -c \
    'mariadb -N -B -uroot -p"$MARIADB_ROOT_PASSWORD" "$MARIADB_DATABASE" -e "SELECT COUNT(*) FROM '"$1"' WHERE '"$2"' IS NOT NULL"' \
    | tr -d '\r\n'
}

snapshot() { # snapshot FILE — liczniki tabel + kolejka ze /stats (jedna linia `klucz=wartość`)
  local out="$1" t
  : > "$out"
  for t in "${TABLES[@]}"; do
    echo "$t=$(count_table "$t")" >> "$out"
  done
  echo "queue=$(api GET /api/wd/v1/stats | jq -c '.data.queue')" >> "$out"
}

value_of() { sed -n "s/^$1=//p" "$2"; }

assert_count_at_least() { # assert_count_at_least FILE TABLE MIN
  local got; got="$(value_of "$2" "$1")"
  [ -n "$got" ] && [ "$got" -ge "$3" ] || fail "$2=$got, oczekiwano ≥ $3 (dane testowe nie powstały)"
}

# 1. Stos testowy + seed + dane przez HTTP.
"$UP" test up mariadb-test migrate api worker fake-llm fake-graph \
  || fail "nie udało się postawić stosu testowego"
wait_api_ready
SEED="$("$UP" test seed)" || fail "seed nie powiódł się"
API_URL="$(sed -n 's/^API_URL=//p' <<<"$SEED")"
ADMIN_EMAIL="$(sed -n 's/^ADMIN_EMAIL=//p' <<<"$SEED")"
ADMIN_PASSWORD="$(sed -n 's/^ADMIN_PASSWORD=//p' <<<"$SEED")"
[ -n "$API_URL" ] || fail "seed: brak API_URL"

# Bootstrap migrate także PRZED zrzutem: `restore.sh` sam uruchamia `app.tools.migrate`, który
# przez `seed_defaults()` dokłada brakujące domyślne modele (idempotentnie). Bez tego kroku stan
# „przed” nie ma tych wierszy, a stan „po” je dostaje i porównanie `models` byłoby z góry różne.
"${COMPOSE[@]}" run --rm --no-deps migrate >"$TMP/migrate-before.out" 2>&1 \
  || fail "migrate przed zrzutem nie powiódł się"

login

DS_ID="$(api POST /api/v1/datasets "$(jq -nc '{name:"bk-dataset"}')" | jq -r '.data.id // empty')"
[ -n "$DS_ID" ] || fail "nie udało się utworzyć datasetu"

DOC_FILE="$TMP/bk-doc.txt"
printf '%s\n' 'Backup restore test document: ala ma kota 0123456789' > "$DOC_FILE"
DOC_SHA="$(sha256sum "$DOC_FILE" | cut -d' ' -f1)"
UPLOAD="$(curl -sS --max-time 60 -X POST -H "Authorization: Bearer $TOKEN" \
  -F "file=@$DOC_FILE;type=text/plain" "$API_URL/api/v1/datasets/$DS_ID/documents")"
DOC_ID="$(jq -r '.data[0].id // empty' <<<"$UPLOAD")"
[ -n "$DOC_ID" ] || fail "upload dokumentu nie powiódł się: $UPLOAD"

api POST "/api/v1/datasets/$DS_ID/chunks" "$(jq -nc --arg d "$DOC_ID" '{document_ids:[$d]}')" >/dev/null
DEADLINE=$((SECONDS + 120)); RUN=""
while [ "$SECONDS" -lt "$DEADLINE" ]; do
  RUN="$(api GET "/api/v1/datasets/$DS_ID/documents?id=$DOC_ID" | jq -r '.data.docs[0].run // empty')"
  case "$RUN" in DONE|FAIL|CANCEL) break ;; esac
  sleep 2
done
[ "$RUN" = "DONE" ] || fail "parsowanie dokumentu nie doszło do DONE (run=$RUN)"

CHAT_ID="$(api POST /api/v1/chats "$(jq -nc '{name:"bk-chat"}')" | jq -r '.data.id // empty')"
[ -n "$CHAT_ID" ] || fail "nie udało się utworzyć czatu"
api POST "/api/v1/chats/$CHAT_ID/sessions" "$(jq -nc '{name:"bk-session"}')" \
  | jq -e '.code == 0' >/dev/null || fail "nie udało się utworzyć sesji"

api POST /api/v1/providers/litellm/instances \
  "$(jq -nc '{instance_name:"bk-test",base_url:"http://fake-llm:8090/v1",api_key:"sekret-bk-1"}')" \
  | jq -e '.code == 0' >/dev/null || fail "nie udało się utworzyć instancji dostawcy"
INST_ID="$(api GET /api/v1/providers/litellm/instances \
  | jq -r '.data[] | select(.instance_name == "bk-test") | .id' | head -n1)"
[ -n "$INST_ID" ] || fail "brak id instancji dostawcy"

INT_DS="$(api POST /api/v1/datasets "$(jq -nc '{name:"bk-integration-dataset"}')" | jq -r '.data.id // empty')"
[ -n "$INT_DS" ] || fail "nie udało się utworzyć datasetu integracji"
# `is_active:false` celowo: aktywna integracja byłaby wzięta przez scheduler workera
# (`integrations/list_due` filtruje `is_active = 1`) i dołożyła dokumenty/kolejkę już po zrzucie
# liczników; sekret (`secret_enc`) zapisuje się niezależnie od flagi, więc odczyt po restore działa.
INT_ID="$(api POST /api/wd/v1/integrations \
  "$(jq -nc --arg ds "$INT_DS" '{type:"sharepoint",name:"bk-integration",dataset_id:$ds,tenant_id:"tenant-e2e",client_id:"client-e2e",client_secret:"fake-graph-secret",site_url:"https://contoso.sharepoint.test/sites/e2e",is_active:false}')" \
  | jq -r '.data.id // empty')"
[ -n "$INT_ID" ] || fail "nie udało się utworzyć integracji"

# 2. Zrzut liczników przed backupem (+ sanity: dane realnie powstały).
snapshot "$TMP/before.txt"
assert_count_at_least "$TMP/before.txt" datasets 2
assert_count_at_least "$TMP/before.txt" documents 1
assert_count_at_least "$TMP/before.txt" chunks 1
assert_count_at_least "$TMP/before.txt" chats 1
assert_count_at_least "$TMP/before.txt" chat_sessions 1
assert_count_at_least "$TMP/before.txt" provider_instances 1
assert_count_at_least "$TMP/before.txt" integrations 1
assert_count_at_least "$TMP/before.txt" users 1
assert_count_at_least "$TMP/before.txt" api_keys 1

# 3. Backup; czas; BACKUP_TS z ostatniej linii.
BK_START=$SECONDS
BK_OUT="$("$ROOT/scripts/backup.sh" --compose-file "$COMPOSE_FILE" --project "$COMPOSE_PROJECT_NAME" \
  --db-service mariadb-test --data-volume test-data --out "$TMP/bk")" || fail "backup nie powiódł się"
BK_TIME=$((SECONDS - BK_START))
BACKUP_TS="$(printf '%s\n' "$BK_OUT" | sed -n 's/^BACKUP_TS=//p' | tail -n1)"
[ -n "$BACKUP_TS" ] || fail "backup: brak BACKUP_TS"

# 3a. Bezpiecznik dumpu (T6): integralność zstd + znacznik końca `-- Dump completed`. Bez tego
# niepełny dump (np. `mariadb-dump` padł pod obciążeniem, a `sh -c 'a | b'` bez pipefail zwraca kod b)
# przechodzi jako sukces backupu — a po restore brakuje ostatniej alfabetycznie tabeli (`users`).
DB_FILE="$TMP/bk/db-$BACKUP_TS.sql.zst"
DB_IMAGE="$(docker inspect --format '{{.Config.Image}}' "$("${COMPOSE[@]}" ps -q mariadb-test)")"
DUMP_BYTES="$(wc -c < "$DB_FILE" | tr -d ' ')"
docker run --rm -i --entrypoint zstd "$DB_IMAGE" -t < "$DB_FILE" \
  || fail "dump bazy uszkodzony (zstd -t)"
DUMP_TAIL="$(docker run --rm -i --entrypoint zstd "$DB_IMAGE" -dc < "$DB_FILE" | tail -n 5)"
grep -q 'Dump completed' <<<"$DUMP_TAIL" || fail "dump bazy ucięty (brak 'Dump completed' w ogonie)"
DUMP_SQL_BYTES="$(docker run --rm -i --entrypoint zstd "$DB_IMAGE" -dc < "$DB_FILE" | wc -c | tr -d ' ')"
echo "backup-restore-test: dump=${DUMP_BYTES}B (po rozpakowaniu ${DUMP_SQL_BYTES}B), users_przed=$(value_of users "$TMP/before.txt")" >&2

# 4. `down -v` własnego projektu, świeży (pusty) stos, restore.
"$UP" test down >/dev/null 2>&1 || fail "down własnego projektu nie powiódł się"
echo "backup-restore-test: --- świeży stos po down -v" >&2
"$UP" test up mariadb-test migrate api worker fake-llm fake-graph \
  || fail "restart stosu na świeżo nie powiódł się"
wait_api_ready
[ "$(count_table datasets)" = "0" ] || fail "świeży stos nie jest pusty (datasets != 0)"

# Tożsamość kontenera bazy tuż przed restore: mariadb-test trzyma dane na tmpfs, więc
# odtworzenie kontenera po imporcie dumpu czyści odtworzoną bazę (objaw: login "not registered").
MARIADB_CID_PRE_RESTORE="$("${COMPOSE[@]}" ps -q mariadb-test)"
MARIADB_IMG_PRE_RESTORE="$(docker inspect --format '{{.Image}}' "$MARIADB_CID_PRE_RESTORE")"

echo "backup-restore-test: --- restore.sh ($BACKUP_TS)" >&2
RS_START=$SECONDS
"$ROOT/scripts/restore.sh" --compose-file "$COMPOSE_FILE" --project "$COMPOSE_PROJECT_NAME" \
  --db-service mariadb-test --data-volume test-data --app-services "api worker" \
  --out "$TMP/bk" --ts "$BACKUP_TS" >"$TMP/restore.out" 2>&1 \
  || { restore_diagnostics; fail "restore nie powiódł się (diagnostyka wyżej)"; }
RS_TIME=$((SECONDS - RS_START))
wait_api_ready

# Diagnostyka (T6): czy kontener bazy przeżył restore bez odtworzenia (tmpfs!). Zmiana cid/obrazu
# po imporcie == odtworzona baza (dane z dumpu przepadły) — to inna przyczyna niż ucięty dump.
MARIADB_CID_POST_RESTORE="$("${COMPOSE[@]}" ps -q mariadb-test)"
MARIADB_IMG_POST_RESTORE="$(docker inspect --format '{{.Image}}' "$MARIADB_CID_POST_RESTORE")"
if [ "$MARIADB_CID_POST_RESTORE" != "$MARIADB_CID_PRE_RESTORE" ] \
  || [ "$MARIADB_IMG_POST_RESTORE" != "$MARIADB_IMG_PRE_RESTORE" ]; then
  echo "backup-restore-test: UWAGA kontener mariadb-test odtworzony po imporcie dumpu (cid ${MARIADB_CID_PRE_RESTORE} -> ${MARIADB_CID_POST_RESTORE}) — tmpfs z odtworzoną bazą wyczyszczony" >&2
fi
POST_RESTORE=1

if [ "${BRT_SABOTAGE:-}" = "1" ]; then
  "${COMPOSE[@]}" exec -T mariadb-test sh -c \
    'mariadb -N -B -uroot -p"$MARIADB_ROOT_PASSWORD" "$MARIADB_DATABASE" -e "DELETE FROM chunks ORDER BY id LIMIT 1"' \
    || fail "sabotage: DELETE nie powiódł się"
fi

# 5. Liczniki po restore == przed backupem; ponowne logowanie tym samym hasłem.
login
snapshot "$TMP/after.txt"
if ! diff -u "$TMP/before.txt" "$TMP/after.txt" > "$TMP/diff.txt"; then
  fail "liczniki po restore różnią się od przed backupem: $(tr '\n' ' ' < "$TMP/diff.txt")"
fi

# 6. Sekrety odtwarzają się: klucz instancji, sekret integracji, blob dokumentu.
login  # token sprzed restartów mógł wygasnąć (TTL access tokenu = 15 min) — odśwież przed krokiem 6
CODE="$(http_code POST /api/v1/providers/litellm/connection "$(jq -nc --arg i "$INST_ID" '{instance_id:$i}')")"
[ "$CODE" = "200" ] && [ "$(jq -r '.code' "$TMP/last.json")" = "0" ] \
  || fail "odczyt klucza instancji po restore nie powiódł się (HTTP $CODE)"
CODE="$(http_code POST "/api/wd/v1/integrations/$INT_ID/test")"
[ "$CODE" = "200" ] && [ "$(jq -r '.data.graph_auth' "$TMP/last.json")" = "ok" ] \
  || fail "test zapisanej integracji po restore nie powiódł się (HTTP $CODE)"
curl -sS --max-time 60 -H "Authorization: Bearer $TOKEN" \
  "$API_URL/api/v1/datasets/$DS_ID/documents/$DOC_ID" -o "$TMP/doc-after.bin"
[ "$(sha256sum "$TMP/doc-after.bin" | cut -d' ' -f1)" = "$DOC_SHA" ] \
  || fail "sha256 bloba dokumentu różni się po restore"

# 7. Rotacja na odtworzonym stosie (nowy klucz tylko w zmiennej; nigdy nie wypisywany).
NEW_KEY="$(openssl rand -hex 32)"
CN_API_KEYS="$(count_nonnull api_keys token_enc)"
CN_MODELS="$(count_nonnull models api_key_enc)"
CN_PROVIDER="$(count_nonnull provider_instances api_key_enc)"
CN_INTEGRATIONS="$(count_nonnull integrations secret_enc)"

echo "backup-restore-test: --- rotacja klucza (dry-run + rotacja)" >&2
"${COMPOSE[@]}" stop api worker || fail "stop api worker nie powiódł się"
ROT_DRY_RC=0
ROT_DRY="$("${COMPOSE[@]}" run --rm --no-deps -e WD_CRYPTO_KEY_NEW="$NEW_KEY" migrate \
  python -m app.tools.rotate_crypto_key --dry-run 2>&1)" || ROT_DRY_RC=$?
[ "$ROT_DRY_RC" -eq 0 ] || fail "rotacja --dry-run rc=$ROT_DRY_RC"
grep -q 'OK (dry-run)' <<<"$ROT_DRY" || fail "rotacja --dry-run: brak 'OK (dry-run)'"

ROT_RC=0
ROT="$("${COMPOSE[@]}" run --rm --no-deps -e WD_CRYPTO_KEY_NEW="$NEW_KEY" migrate \
  python -m app.tools.rotate_crypto_key 2>&1)" || ROT_RC=$?
[ "$ROT_RC" -eq 0 ] || fail "rotacja rc=$ROT_RC"
grep -qx 'OK' <<<"$ROT" || fail "rotacja: brak linii 'OK'"

check_rot_line() { # check_rot_line KEY EXPECTED — dokładna zgodność z C2 (liczba wierszy nie-NULL)
  local got; got="$(sed -n "s/^$1: \\([0-9]*\\)$/\\1/p" <<<"$ROT")"
  [ -n "$got" ] || fail "rotacja: brak linii '$1: <n>'"
  [ "$got" = "$2" ] || fail "rotacja: $1=$got, oczekiwano $2 (wiersze nie-NULL przed rotacją)"
}
check_rot_line api_keys.token_enc "$CN_API_KEYS"
check_rot_line models.api_key_enc "$CN_MODELS"
check_rot_line provider_instances.api_key_enc "$CN_PROVIDER"
check_rot_line integrations.secret_enc "$CN_INTEGRATIONS"
[ "$CN_API_KEYS" -ge 1 ] || fail "rotacja nie przeszyfrowała api_keys"
[ "$CN_PROVIDER" -ge 1 ] || fail "rotacja nie przeszyfrowała provider_instances"
[ "$CN_INTEGRATIONS" -ge 1 ] || fail "rotacja nie przeszyfrowała integrations"

# 7d. api z NOWYM kluczem czyta sekrety; 7e. api ze STARYM kluczem już nie.
echo "backup-restore-test: --- api z nowym kluczem" >&2
printf 'services:\n  api:\n    environment:\n      WD_CRYPTO_KEY: %s\n' "$NEW_KEY" > "$TMP/override-new-key.yml"
chmod 600 "$TMP/override-new-key.yml"
"${COMPOSE[@]}" -f "$TMP/override-new-key.yml" up -d --wait --no-deps api || fail "start api z nowym kluczem"
wait_api_ready
login  # po restarcie api token sprzed restartu może być nieważny/wygasły
CODE="$(http_code POST /api/v1/providers/litellm/connection "$(jq -nc --arg i "$INST_ID" '{instance_id:$i}')")"
[ "$CODE" = "200" ] && [ "$(jq -r '.code' "$TMP/last.json")" = "0" ] \
  || fail "api z nowym kluczem nie odczytał klucza instancji (HTTP $CODE)"
CODE="$(http_code POST "/api/wd/v1/integrations/$INT_ID/test")"
[ "$CODE" = "200" ] && [ "$(jq -r '.data.graph_auth' "$TMP/last.json")" = "ok" ] \
  || fail "api z nowym kluczem nie odczytał sekretu integracji (HTTP $CODE)"

echo "backup-restore-test: --- api z powrotem ze starym kluczem" >&2
"${COMPOSE[@]}" up -d --wait --no-deps api --force-recreate || fail "restart api ze starym kluczem"
wait_api_ready
login  # świeży token po restarcie — inaczej 401 mógłby fałszywie „potwierdzić” negatyw
CODE="$(http_code POST /api/v1/providers/litellm/connection "$(jq -nc --arg i "$INST_ID" '{instance_id:$i}')")"
NEG_FAILED=false
if [ "$CODE" -ge 400 ]; then NEG_FAILED=true; fi
ERR_CODE="$(jq -r 'if .code != null then .code else 0 end' "$TMP/last.json" 2>/dev/null || echo 0)"
if [ "$ERR_CODE" != "0" ]; then NEG_FAILED=true; fi
[ "$NEG_FAILED" = true ] || fail "stary klucz nadal odczytuje sekret (HTTP $CODE)"

echo "backup-restore-test: OK (backup ${BK_TIME}s, restore ${RS_TIME}s, razem $((BK_TIME + RS_TIME))s)"
