# contract-recorder — nagrywanie kontraktu API RAGFlow (SP-5, WP E0-5b)

`record.py` stawia **oficjalny** stos RAGFlow danej wersji (obrazy upstream, compose przepisany
z `docker/` taga) dołącza nasz `fake-llm`, zakłada konto, rejestruje modele fake jako
„OpenAI-API-Compatible", ustawia modele domyślne tenanta i tworzy klucz API. Po każdym biegu stos
jest usuwany (`docker compose down -v --remove-orphans`), także przy błędzie i Ctrl-C.

## Wymagania

- Docker (daemon na hoście) z `docker compose` v2 — uruchamiane z kontenera agenta działa,
  bo `build:` wysyła kontekst przez API; **bind-mountów nie używamy** (ścieżki `/host/...`
  nie przechodzą do daemona).
- ~24 GB obrazów (zmierzone `docker image ls`): `infiniflow/ragflow:v0.24.0` 11,2 GB,
  `infiniflow/ragflow:v0.27.2` 12,7 GB, `elasticsearch:8.11.3` 2,1 GB, `mysql:8.0.39` 785 MB,
  `mysql:8.0.40` 826 MB, `satantime/minio-server:RELEASE.2025-06-13T11-33-47Z` 240 MB,
  `pgsty/silo:RELEASE.2026-08-06T00-00-00Z` 216 MB, `valkey/valkey:8` 165 MB.
- Host: ES wymaga `vm.max_map_count >= 262144` i kilku GB RAM (limit ES = 8 GiB jak upstream),
  ~2,5 GB wolnego na wolumeny podczas biegu.
- Pierwszy start RAGFlow (migracje, inicjalizacja ES) trwa minuty — `wait_ready` czeka do 900 s.

## Użycie

```bash
# tylko stos + bootstrap konta i modeli
uv run --script tools/contract-recorder/record.py --version v0.24.0 --bootstrap-only
uv run --script tools/contract-recorder/record.py --version v0.27.2 --bootstrap-only

# pełne nagranie: stos + bootstrap + scenariusze + golden files
uv run --script tools/contract-recorder/record.py --version v0.24.0
uv run --script tools/contract-recorder/record.py --version v0.27.2
# iteracja nad jednym scenariuszem (stos startuje kilka minut, więc to oszczędza czas):
uv run --script tools/contract-recorder/record.py --version v0.24.0 --scenarios 'scenarios/datasets_crud.yaml'
```

`--scenarios` przyjmuje jeden lub więcej wzorców glob (bez opcji: `scenarios/*.yaml`); pliki ze wszystkich wzorców są łączone bez duplikatów i sortowane.

Po bootstrapie na stdout pada jedna linia
`BOOTSTRAP OK version=<ver> chat=<llm_id> embd=<embd_id> seconds=<s>` (kod 0).
Klucz API nie jest wypisywany. Przy pełnym nagraniu: jedna linia na scenariusz
`SCENARIO <nazwa> OK|FAIL files=<n>` (przy FAIL — dodatkowo przyczyna; pozostałe
scenariusze lecią dalej) i na końcu
`RECORD version=<ver> scenarios=<n> files=<n> fail=<m> seconds=<s>`,
kod wyjścia 0 ⇔ `fail == 0`.

Logi biegu (dowód): `results/bootstrap-<ver>.log`, `results/record-<ver>.log`.

## E2-0: `--keep`/`--attach`/`--out`, `auth: second`

Start stosu trwa minuty i powtarza się przy każdym biegu, dlatego sesja bootstrapu może przeżyć
między biegami:

```bash
# 1. biegnij i ZOSTAW stos: po bootstrapie sesja leci do /tmp/wd-rec-session-<ver>.json
uv run --script tools/contract-recorder/record.py --version v0.24.0 \
  --scenarios 'scenarios/datasets_crud.yaml' --keep
# 2. kolejne biegi dołączają do tego samego stosu (bez compose i bootstrapu)
uv run --script tools/contract-recorder/record.py --version v0.24.0 \
  --scenarios 'scenarios/retrieval.yaml' --attach
# 3. strojenie scenariusza bez ruszania złota z repo
uv run --script tools/contract-recorder/record.py --version v0.24.0 \
  --scenarios 'scenarios/retrieval.yaml' --attach --out /tmp/golden
```

- `--keep` — zapisuje sesję (`dataclasses.asdict`, chmod 600) i nie robi końcowego `down -v`
  (także przy błędzie — zostaje do diagnozy); stos trzeba wtedy sprzątnąć ręcznie:
  `docker compose -p wd-rec-v0-24-0 -f tools/contract-recorder/compose.v0.24.0.yml down -v --remove-orphans`.
- `--attach` — pomija compose i bootstrap, wczytuje sesję z `/tmp/wd-rec-session-<ver>.json`;
  brak pliku → komunikat na stderr i kod wyjścia 2. Nic nie sprząta.
- `--keep` i `--attach` wykluczają się wzajemnie. Bez tych opcji cykl życia bez zmian
  (`down -v` przed bootstrapem i po scenariuszach).
- `--out DIR` — katalog główny złota pisany zamiast `backend/tests/contract/golden`.

`bootstrap()` zakłada teraz **drugie konto** (`recorder2@wd.test` / `recorder2`, hasło jak pierwsze,
bez modeli) i tworzy dla niego klucz API. Pola `api_key_2`/`auth_2` sesji obsługują tryby
`auth: second` i `auth: second_jwt` (C1) — konto 2 nie widzi zasobów konta 1.

## E6-0: tryb `--mcp`

`--mcp` (tylko `--version v0.27.2`; z `v0.24.0` kod wyjścia 2) dokłada do wszystkich wywołań
`docker compose` override `compose.v0.27.2.mcp.yml`:

```bash
uv run --script tools/contract-recorder/record.py --version v0.27.2 --mcp --keep \
  --scenarios 'scenarios/metadata_e6.yaml' 'mcp_scenarios/*.yaml'
# kolejne biegi (bez stawiania stosu): --attach --mcp --scenarios 'mcp_scenarios/*.yaml'
```

- Override dodaje do usługi `ragflow` flagi serwera MCP upstream (`--enable-mcpserver`,
  `--mcp-host=0.0.0.0`, `--mcp-port=9382`, `--mcp-base-url=http://127.0.0.1:9380`,
  `--mcp-script-path=/ragflow/mcp/server/server.py`, `--mcp-mode=host`) — obie flagi bazowe
  (`--enable-adminserver`, `--init-model-provider-tables`) zostają — i publikuje port
  **19382 → 9382**. `command` jest zastępowany, `ports` skalane z plikiem bazowym.
- Podgląd scalonej konfiguracji bez stawiania stosu:
  `docker compose -p wd-rec-v0-27-2 -f tools/contract-recorder/compose.v0.27.2.yml -f tools/contract-recorder/compose.v0.27.2.mcp.yml config`.
- Bez `--mcp` bieg jest identyczny jak dotąd: jeden plik compose, bez override.
- Wzorce spod `mcp_scenarios/` idą do `mcp_runner.py` (rozpoznanie po katalogu), reszta do `runner.py`.
  MCP z hosta: `http://host.docker.internal:19382`. Sesja `--keep --mcp` to ta sama
  `/tmp/wd-rec-session-v0.27.2.json`.
- `mcp_runner.py` (klient = `mcp`, wersja w `# /// script dependencies` `record.py`, nie w
  `backend/pyproject.toml`): kroki `{id, transport: streamable_http|sse, op: initialize|list_tools|call_tool,
  tool?, arguments?, auth?, record?, expect_error?, capture?}` oraz krok pomocniczy `op: http`
  (pola jak w `runner.py`). Złoto: `backend/tests/contract/golden/v0.27.2/mcp/<scenariusz>--<nr>-<id>.json`
  o kształcie `{"request": {transport, op, tool, arguments, auth}, "outcome": "ok"|"error",
  "result": <model_dump wyniku klienta, po normalizacji>}`; przy błędzie klienta/HTTP
  `result = {error_type, message, http_status}`. Szczegóły i API klienta: `work/wp/E6-0/reports/T3a-notes.md`.

## Scenariusze (runner.py, normalize.py)

Runner czyta `scenarios/*.yaml` (format zamrożony w briefie `work/wp/E0-5b/tasks/sp5-scenarios.md`):
kroki `method`/`path`/`query`/`json`/`multipart`, `capture` (ścieżka kropkowa w odpowiedzi →
zmienna podstawiana w `{nazwa}`), `versions` (krok tylko dla wybranych wersji; numer kroku
i tak zajęty), `poll` (powtarzaj aż `until`, nagrywana jest ostatnia odpowiedź), `stream: true`
(zapis `.sse`), `record: false` (krok pomocniczy, bez pliku golden) i `rules`
(`exact|type|ignore` per pole — notatka dla przyszłych testów kontraktowych E2, podczas
nagrywania nieużywana). Nagłówek `Authorization: Bearer <api_key>` dodaje runner.

Golden files: `backend/tests/contract/golden/<ver>/<endpoint>/<scenariusz>--<nr kroku>.json|.sse`,
gdzie `<endpoint>` = ścieżka szablonu bez `/api/v1/`, segment `{…}` z okalającymi ukośnikami →
`___`, pozostałe `/` → `__` (np. `datasets`, `datasets___documents`,
`chats_openai___chat__completions`). `.json` = `{"request": {method, path, query, body},
"status", "headers": {content-type}, "body"}` (indent 2, `ensure_ascii=False`); dla kroków
`multipart` request `body` jest `null` (plik: `fixtures/ragflow_intro.txt`), a odpowiedź
niebędąca JSON-em (download dokumentu) trafia do `body` jako string. `.sse` = surowe bajty
strumienia po normalizacji wartości w ramkach `data:` (ramki JSON serializowane
`ensure_ascii=False, separators=(",", ":")`, prefiks `data:`/`data: ` zachowany 1:1,
ramki nie-JSON jak `[DONE]` bez zmian, terminator `\n\n` zachowany).

Normalizacja wartości (normalize.py) — reguły C2: id (32 znaki hex lub przechwycone)
→ `<ID:<rodzaj>#<n>>` (rodzaj = nazwa zmiennej z `capture` bez `_id`; numeracja per rodzaj
wg pierwszego wystąpienia), `*_time` (int, ms) → `<TS_MS>`, daty HTTP → `<HTTP_DATE>`,
`YYYY-MM-DD HH:MM:SS` → `<DATETIME>`, pola similarity → `<FLOAT>`, klucze API/tokenów →
`<TOKEN>`. Reguły dodane dla determinizmu (uzasadnienie: `docs/spikes/SP-5.md`):
`created` (sekundy) → `<TS_S>`, `create_timestamp`/`process_duration` → `<FLOAT>`,
`progress_msg` (czasy zadań w treści) → `<IGNORE>`.

Scenariusze (nazwy plików dosłownie z C2): `datasets_crud`, `documents_parse`, `chunks_list`,
`retrieval`, `chat_session`, `completion`, `openai_compat`. Każdy sprząta po sobie
(delete datasetu/czatu na końcu, `record: false`). Ciała żądań i trasy pochodzą z
upstreamowych testów HTTP danego taga (`test/testcases/test_http_api`, v0.27.2 dodatkowo
`test/testcases/restful_api`); różnice tras między wersjami są rozwiązane polem `versions`
(np. parse: `/datasets/{id}/chunks` w v0.24.0 vs `/datasets/{id}/documents/parse` w v0.27.2;
update sesji: PUT vs PATCH; completion RESTful i OpenAI-compat `/openai/{id}` tylko v0.27.2).

Testy jednostkowe (bez Dockera):

```bash
uv run --no-project --with pytest==9.1.1 --with pyyaml==6.0.3 --with httpx==0.28.1 \
  --with pycryptodomex==3.23.0 --with mcp==1.30.0 pytest tools/contract-recorder/tests -q
```

## Stos

| usługa | obraz | uwagi |
|---|---|---|
| `ragflow` | `infiniflow/ragflow:v0.24.0` / `v0.27.2` | jedyny publikowany port: **18380 → 9380** (HTTP API) |
| `es01` | `elasticsearch:8.11.3` | `mem_limit` 8 GiB jak upstream, v0.27.2 dodaje tmpfs `/tmp` |
| `mysql` | `mysql:8.0.39` (v0.24.0) / `mysql:8.0.40` (v0.27.2) | `MYSQL_DATABASE=rag_flow` zamiast `init.sql` |
| `minio` | v0.24.0: `satantime/minio-server:RELEASE.2025-06-13T11-33-47Z`; v0.27.2: `pgsty/silo:RELEASE.2026-08-06T00-00-00Z` | patrz niżej |
| `redis` | `valkey/valkey:8` | v0.24.0 `allkeys-lru`, v0.27.2 `volatile-lru` |
| `fake-llm` | budowany z `../fake-llm` | w sieci pod `http://fake-llm:8090/v1` |

Wolumeny nazwane (esdata01, mysql_data, minio_data, redis_data) — znikają z `down -v`.
`TZ=Asia/Shanghai` we wszystkich usługach, jak upstream (spójność dat dla golden files).

### Odchylenie od upstream (minio, tylko v0.24.0)

Upstreamowa referencja `quay.io/minio/minio:RELEASE.2025-06-13T11-33-47Z` przestała być
pobieralna: repo `quay.io/minio/minio` (i usunięte `minio/minio` na Docker Hub) jest prywatne
od 2026-09-24 — anonimowy pull zwraca 401. `compose.v0.24.0.yml` używa
`satantime/minio-server:RELEASE.2025-06-13T11-33-47Z` — mirrora **dokładnie tej samej** wersji
(binarka raportuje `RELEASE.2025-06-13T11-33-47Z`, commit `a6c538c5a113a588d49b4f3af36ae3046cfa5ac6`;
labelki obrazu: maintainer/vendor „MinIO Inc", baza ubi9-micro jak w oryginale).
v0.27.2 nie dotyczy — upstream sam zastąpił MinIO przez `pgsty/silo`.

## Bootstrap (rf_bootstrap.py)

Sekwencja z upstreamowych testów HTTP (`test/testcases/conftest.py`) danej wersji:

- **v0.24.0** (legacy `/v1`): `POST /v1/user/register` → `POST /v1/user/login` (nagłówek
  `Authorization`) → `POST /v1/llm/add_llm` × 2 (czat `fake-chat`, embedding `fake-embed-1024`,
  `api_base` `http://fake-llm:8090/v1`) → `GET /v1/llm/my_llms` (odczyt faktycznych nazw
  z sufiksem `___OpenAI-API`) → `GET /v1/user/tenant_info` → `POST /v1/user/set_tenant_info`
  → `POST /v1/system/new_token`.
- **v0.27.2** (RESTful `/api/v1`): `POST /api/v1/users` → `POST /api/v1/auth/login` →
  `PUT /api/v1/providers` + `POST /api/v1/providers/OpenAI-API-Compatible/instances` →
  `GET /api/v1/models` → `PATCH /api/v1/models/default` × 2 → `GET /api/v1/models/default` →
  `POST /api/v1/system/tokens`.

Wersji API nie podaje się w konfiguracji — `bootstrap()` rozpoznaje ją po trasie `system/ping`
(v0.24.0 odpowiada na `/v1/system/ping`, v0.27.2 na `/api/v1/system/ping`). `wait_ready` odpytuje
`GET /v1/system/healthz` (istnieje w obu tagach) co 5 s, do 900 s.
Hasło (`recorder123`) jest przed wysłaniem szyfrowane RSA kluczem publicznym `conf/public.pem`
z repo upstream (ten sam plik w obu tagach) — tak robi frontend/CLI upstreamu.

## Znane pułapki

- **Bind-mounty nie działają** — daemon Dockera jest na hoście; dlatego compose nic nie montuje:
  obrazy RAGFlow mają w sobie `entrypoint.sh`, `service_conf.yaml.template` i konfigurację nginxa.
- **Port 18380 jest wspólny** dla obu wersji — biegi robić sekwencyjnie (każdy bieg sam sprząta).
- **quay.io/minio/minio 401** — patrz „Odchylenie od upstream"; nie zmieniać na inne wersje MinIO.
- Pierwsze uruchomienie buduje obraz `fake-llm` (`build: ../fake-llm`) — wymaga sieci na
  `python:3.13-slim` i obrazu `uv` z ghcr.
- `docker compose logs --tail 200 ragflow` (upstream: usługa `ragflow`) przy diagnozie;
  `record.py` sam wypisze te logi na stderr przy porażce przed `finally`.
