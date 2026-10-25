# Wawelsky Dragon

> Lekki system RAG zgodny z API RAGFlow. Zastępuje RAGFlow u klienta: ta sama znajoma powierzchnia UI
> i te same trasy `/api/v1`, ale **jeden** stos kontenerów i **jedna** baza MariaDB.

## 1. Czym jest Wawelsky Dragon

Wawelsky Dragon (WD) to samodzielny system RAG: baza wiedzy (datasety, dokumenty, parsowanie, chunki,
embeddingi) oraz czat i wyszukiwanie z cytowaniami. Powstał jako zamiennik RAGFlow: dla użytkownika
wygląda znajomo (te same sekcje: Home · Datasets · Chat · Search · Files · Settings · Admin), a dla
integracji jest podmianą 1:1.

- **Zgodność API**: `/api/v1` w kształcie RAGFlow v0.27 (+ shim v0.24 dla starszych klientów), a dodatkowo
  natywne endpointy klienta hub-compat `/api/users…`, `/user-api/…`, `/sharepoint-sync-api/…`. hub-compat przechodzi na WD
  **zmianą URL-i i kluczy w env, bez zmian w kodzie**.
- **Operacyjnie lekki**: MariaDB 11.8, pliki na wolumenie, kilka kontenerów, start `docker compose up -d`.
- **Dla kogo**: administrator klienta wdrażający WD obok (docelowo zamiast) RAGFlow.

Pełny obraz: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) (cele, decyzje, moduły);
stan faktyczny tego, co powstało: [`docs/BIG-PICTURE.md`](docs/BIG-PICTURE.md).

## 2. Architektura w skrócie

| Usługa | Rola | Port na hoście |
|---|---|---|
| `mariadb` | jedyna baza: metadane, wektory, FULLTEXT, kolejka zadań, cache LLM, sesje | — (tylko sieć wewnętrzna) |
| `migrate` | jednorazowo: `alembic upgrade head`, seed modeli, konto admina | — |
| `api` | FastAPI (uvicorn): trasy RAGFlow/hub-compat/WD, SSE, health | — (za `web`) |
| `worker` | kolejka zadań: parsowanie, chunkowanie, embeddingi, scheduler integracji | — |
| `web` | SPA (React + MUI) serwowana przez Bun + reverse proxy do `api` | **8080** (jedyny publiczny) |
| `fake-llm` | deterministyczny stub OpenAI API do prób bez klucza (profil `fake`) | — (tylko sieć wewnętrzna, `http://fake-llm:8090/v1`) |

Kontenery łączy sieć `wd-net`, a dane trzymają dwa wolumeny: `db-data` (baza) i `app-data` (`/data`:
oryginały dokumentów i obrazy chunków). TLS terminuje zewnętrzny reverse proxy/ingress przed `web`.
Źródło prawdy to plik [`docker-compose.yml`](docker-compose.yml); opis w
[`docs/modules/infrastruktura.md`](docs/modules/infrastruktura.md) i
[`docs/architecture/11-infrastruktura.md`](docs/architecture/11-infrastruktura.md).

## 3. Wymagania

- Docker Engine z Compose v2 (`docker compose version`), Linux x86-64.
- Pamięć: **domyślnie ≥ 16 GB RAM** dla całego stosu (limit kontenera MariaDB 8 GB, pula InnoDB 6 GB, `api`
  1 GB, `worker` 2 GB, `web` 256 MB).
- Miejsce na dysku: **≥ 50 GB** (baza + pliki + kopie zapasowe).
- Dostęp do bramki LLM zgodnej z OpenAI (chat + embeddings + rerank).

Sizing puli InnoDB dobiera się do rozmiaru korpusu (pula ≥ 1,3 × (tabela wektorów + `chunks`)):

| korpus (w sumie skanowany jednym zapytaniem) | wymiar | dane | pula InnoDB | limit kontenera |
|---|---|---|---|---|
| ≤ 20 tys. chunków | 3072 | ok. 0,4 GB | 1 GB | 2 GB (wariant minimalny) |
| 100 tys. | 1024 | ok. 1,0 GB | 2 GB | 4 GB |
| 100 tys. | 3072 (domyślny) | ok. 1,9 GB | **6 GB (domyślnie)** | **8 GB (domyślnie)** |
| 300 tys. | 3072 | ok. 5,7 GB | nie mieści się w 8 GB — wymaga > 8 GB RAM lub partycjonowania | — |

Wariant minimalny (mniejszy host) ustawia `WD_MARIADB_MEMORY=2g` i `WD_MARIADB_BUFFER_POOL=1G`; nadaje się
tylko dla zbiorów ≤ ~20 tys. chunków — przy 100 tys. chunków wymiaru 3072 każdy retrieval czyta dysk
(p95 ~7,7 s zamiast ~1,3 s). Wyniki pomiarów: [`docs/perf/E5-1b.md`](docs/perf/E5-1b.md).

Szczegółowa tabela zasobów i skalowanie: [`docs/architecture/11-infrastruktura.md`](docs/architecture/11-infrastruktura.md)
§10 (`worker` skaluje się przez `--scale worker=N`).

## 4. Szybki start produkcyjny

Wszystkie komendy uruchamiaj z katalogu repo (tam, gdzie leży `docker-compose.yml`).

1. **Wygeneruj plik sekretów.** Skrypt tworzy `.env` na podstawie `.env.example`, wpisując losowe
   `WD_DB_PASSWORD`, `WD_DB_ROOT_PASSWORD`, `WD_SECRET_KEY`, `WD_CRYPTO_KEY`, `WD_HUB_COMPAT_API_SECRET`
   i ustawiając prawa `0600`. Istniejącego `.env` nie nadpisze bez `--force`.

   ```bash
   scripts/gen-secrets.sh
   ```

2. **Uzupełnij `.env`.** Wartości wpisuj bez cudzysłowów; placeholdery `<…>` zastąp własnymi:
   - `WD_LLM_BASE_URL=https://<twoja-bramka-llm>/v1` — adres bramki OpenAI-compatible (np. LiteLLM);
   - `WD_LLM_API_KEY=<klucz-bramki>`;
   - `WD_ADMIN_EMAIL=<admin@twoja-domena>` i `WD_ADMIN_PASSWORD=<hasło-admina>` — konto superusera,
     zakładane raz, przy pierwszym starcie (przy kolejnych ignorowane);
   - opcjonalnie: `WD_PUBLIC_BASE_URL` (adres, pod którym WD będzie widoczne — linki i callback OIDC),
     `WD_HTTP_PORT` (domyślnie 8080), `WD_HUB_COMPAT_API_SECRET` (endpointy dla hub-compat), `KEYCLOAK_*` (SSO).

   Pełny katalog zmiennych: [`docs/architecture/11-infrastruktura.md`](docs/architecture/11-infrastruktura.md) §5.

3. **Uruchom stos** (pierwszy start buduje obrazy i wykonuje migracje):

   ```bash
   docker compose up -d --build --wait
   ```

4. **Sprawdź zdrowie** (kontener `web` to jedyny publiczny port):

   ```bash
   docker compose ps
   curl -fsS http://localhost:8080/healthz
   curl -fsS http://localhost:8080/health/ready
   curl -fsS http://localhost:8080/api/v1/system/healthz
   ```

   `/healthz` potwierdza, że `web` odpowiada i widzi `api`; `/health/ready` — że baza jest osiągalna,
   a schemat aktualny (wersja migracji zgodna z obrazem); `/api/v1/system/healthz` — że baza i magazyn
   plików (`storage`) odpowiadają.

5. **Pierwsze logowanie.** Otwórz `http://localhost:8080` i zaloguj się e-mailem/hasłem z `WD_ADMIN_*`
   (krok 2). Dalej przez UI: dodaj dataset, wgraj dokumenty i uruchom parsowanie, potem czat z cytowaniami.
   Jeśli ustawisz `KEYCLOAK_*`/`WD_OIDC_*`, dojdzie logowanie przez SSO.

6. **Diagnostyka i zatrzymanie.**

   ```bash
   docker compose logs -f api worker
   docker compose down
   ```

Kolejne kroki administracyjne (dostawcy modeli, OIDC, klucze API, SharePoint, backup/restore, rotacja
`WD_CRYPTO_KEY`, aktualizacja wersji, migracja z RAGFlow, przepięcie hub-compat, typowe awarie) opisuje
[`docs/runbooks/admin.md`](docs/runbooks/admin.md).

## 5. Mapa dokumentacji

| Dokument | Zawartość |
|---|---|
| [`docs/BIG-PICTURE.md`](docs/BIG-PICTURE.md) | co realnie powstało: moduły, przepływy, odchyłki od specyfikacji |
| [`docs/runbooks/admin.md`](docs/runbooks/admin.md) | runbook administratora: konfiguracja i utrzymanie WD |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | architektura i decyzje projektowe (mapa całości) |
| [`docs/runbooks/kubernetes-ovh.md`](docs/runbooks/kubernetes-ovh.md) | wdrożenie dev/prod na Kubernetesie (CI/CD, Harbor, Argo CD), sekrety, rollback |
| [`docs/runbooks/backup-restore.md`](docs/runbooks/backup-restore.md) | kopie zapasowe, odtworzenie, rotacja klucza szyfrującego |
| (dokumentacja poza repozytorium publicznym) | przepięcie klienta hub-compat z RAGFlow na WD — część prywatna |
| [`docs/security/checklista-H.md`](docs/security/checklista-H.md) | checklista bezpieczeństwa H1–H17 z dowodami |
| [`docs/README.md`](docs/README.md) | spis całej dokumentacji |
| [`docs/modules/`](docs/modules/) | dokumentacja modułów (stan faktyczny po kolejnych pakietach pracy) |

## 6. Rozwój i testy

Trzy wyrocznie (uruchamiane z korzenia repo) mają rosnący zakres: `./.claude/verify-fast.sh` to testy
jednostkowe + lint + typy (~1–2 min, tyle wystarczy przy zwykłej zmianie), `./.claude/verify.sh` dokłada
testy z bazą MariaDB i kontrakty API, a `./.claude/verify-full.sh` dodatkowo e2e Playwright, budowę obrazów
i smoke ewaluacji. Każda kończy się dokładnie jedną linią werdyktu `WYROCZNIA ZIELONA` (kod 0), a ostatnią
linią logu jest `rc=<kod>` (kod wyjścia procesu — także przy czerwieni i sygnałach).

```bash
./.claude/verify-fast.sh
```

## Licencja

Wawelsky Dragon jest udostępniany na licencji Apache License 2.0 (plik [`LICENSE`](LICENSE)).
Copyright 2026 Łukasz Różewicz.

Projekt jest kompatybilny z API RAGFlow v0.27.2 i zawiera fragmenty pochodzące z RAGFlow
(InfiniFlow, Apache-2.0) — zob. [`NOTICE`](NOTICE) oraz [`docs/licensing/ragflow-provenance.md`](docs/licensing/ragflow-provenance.md).

## English (short)

**What it is.** Wawelsky Dragon (WD) is a lightweight RAG system that is API-compatible with RAGFlow
(`/api/v1`, v0.27 + a v0.24 shim) and additionally serves hub-compat's native endpoints (`/user-api`,
`/sharepoint-sync-api`). It replaces RAGFlow at hub-compat: a familiar UI and integration swap by
configuration only, with a single MariaDB database and a handful of containers.

**Architecture.** `mariadb` (data, vectors, full-text, task queue, LLM cache), a one-shot `migrate`,
`api` (FastAPI), `worker` (parsing, chunking, embeddings, integration scheduler) and `web`
(Bun-served SPA + reverse proxy). Only `web` publishes a port (8080) on the `wd-net` network; data
lives in the `db-data` and `app-data` volumes.

**Requirements.** Docker with Compose v2; ≥ 16 GB RAM (MariaDB container 8 GB, InnoDB pool 6 GB) and
≥ 50 GB disk by default. Smaller hosts can use the minimal variant (`WD_MARIADB_MEMORY=2g`,
`WD_MARIADB_BUFFER_POOL=1G`), suitable for corpora up to ~20k chunks.

**Quick start (production).**
1. `scripts/gen-secrets.sh` — creates a `0600` `.env` from `.env.example` with random secrets.
2. Fill in `.env`: `WD_LLM_BASE_URL`, `WD_LLM_API_KEY`, `WD_ADMIN_EMAIL`, `WD_ADMIN_PASSWORD`
   (optionally `WD_PUBLIC_BASE_URL`, `WD_HTTP_PORT`, `WD_HUB_COMPAT_API_SECRET`, `KEYCLOAK_*`).
3. `docker compose up -d --build --wait` — `--build` is required on first start and after an update,
   otherwise an existing `wawelsky/*:latest` image on the host is reused instead of rebuilt.
4. `docker compose ps`, `curl -fsS http://localhost:8080/healthz`.
5. Open `http://localhost:8080` and log in with the `WD_ADMIN_*` account.
6. `docker compose logs -f api worker`, `docker compose down`.

**Tests.** `./.claude/verify-fast.sh` (unit + lint + types), `./.claude/verify.sh` (+ MariaDB and API
contracts), `./.claude/verify-full.sh` (+ Playwright e2e, image builds, eval smoke).

**Links.** [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md),
[`docs/BIG-PICTURE.md`](docs/BIG-PICTURE.md),
[`docs/runbooks/admin.md`](docs/runbooks/admin.md),
[`docs/README.md`](docs/README.md).

## License

Wawelsky Dragon is licensed under the Apache License 2.0 (see [`LICENSE`](LICENSE)).
Copyright 2026 Łukasz Różewicz.

The project is compatible with the RAGFlow v0.27.2 API and contains portions derived from RAGFlow
(InfiniFlow, Apache-2.0) — see [`NOTICE`](NOTICE) and [`docs/licensing/ragflow-provenance.md`](docs/licensing/ragflow-provenance.md).
