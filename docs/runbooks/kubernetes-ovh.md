# Wdrożenie na Kubernetesie (OVH, Argo CD)

Instancje projektu: **dev** `https://dragon.dev.lucasnextgen.com` i **prod** `https://dragon.lucasnextgen.com`.
To odrębna ścieżka od `docker-compose.yml` (ten sam kod i te same obrazy, inne uruchomienie).

## Flow

```
gałąź ──PR──► main ───────────────► tag v1.2.3 (GitHub Release)
   │            │                        │
 test, build,  build 3 obrazów,        te same obrazy
 Trivy         Harbor, wdrożenie DEV   (bez przebudowy), wdrożenie PROD
```

- **PR do `main`:** wspólny workflow `lrozewicz/.github` buduje trzy obrazy (`backend`, `web`, `searxng`), uruchamia etapy `test`
  (backend: `ruff`, `mypy`, `lint-imports`, testy jednostkowe; web: typy, ESLint/Prettier, vitest, test serwera, bundle budget) i skanuje je Trivy.
  Wymagany check: `pr / checks`. Nic nie jest publikowane.
- **Merge do `main`:** obrazy trafiają do Harbora (`harbor.lucasnextgen.com/wawelsky-dragon/<obraz>:<hash drzewa>`), CI zapisuje tag
  `dev-<hash>` w repozytorium `platform-gitops` (`apps/wawelsky-dragon/dev/values.yaml`), Argo CD wdraża w ~3 min.
- **Tag `v*` na commicie z `main`:** te same obrazy dostają tag `prod-<hash>` i `v1.2.3`; wdrożenie na prod czeka na zatwierdzenie
  (*Approve* w GitHubie, jedno na całe wydanie).

## Składniki

Jeden `Deployment` na składnik (chart `webapp` w `platform-gitops`, tryb `components`):

| Składnik | Obraz | Rola |
|---|---|---|
| `web` | `web` | SPA + reverse proxy do `api` i `mcp`; jedyny, który widać z internetu (`/healthz`) |
| `api` | `backend` | FastAPI; init container wykonuje migracje, zasiew modeli i konto admina (`python -m app.tools.migrate`) |
| `worker` | `backend` | kolejka zadań; startuje po gotowości `api` |
| `mcp` | `backend` | serwer MCP (`/mcp`, `/sse`, `/messages/` przez `web`) |
| `searxng` | `searxng` | wyszukiwanie w internecie dla Agenta (`http://searxng:8080`) |
| baza | `mariadb:11.8.9` | MariaDB z mariadb-operatora, codzienne kopie do PVC i do OVH Object Storage |

`api` i `worker` współdzielą wolumen `/data` (oryginały dokumentów, obrazy chunków), kopiowany off-site przez Velero.
Procesy działają jako UID `10001` z systemem plików tylko do odczytu (zapisywalne: `/tmp` i `/data`); searxng jako `977`.

## Konfiguracja

- Wspólna: `platform-gitops/apps/wawelsky-dragon/values.yaml`; per środowisko: `apps/wawelsky-dragon/{dev,prod}/values.yaml`
  (host, `WD_PUBLIC_BASE_URL`, rozmiary bazy i wolumenów). Tag obrazu (`image.tag`) ustawia wyłącznie CI.
- Sekrety (SealedSecret, `apps/wawelsky-dragon/<env>/sealed-app.yaml`, `sealed-searxng.yaml`): `WD_SECRET_KEY`, `WD_CRYPTO_KEY`,
  `WD_HUB_COMPAT_API_SECRET`, `WD_LLM_*`, `WD_ADMIN_*`, `SEARXNG_SECRET`. **`WD_CRYPTO_KEY` szyfruje dane w bazie — nie zmieniać na
  działającej instalacji** (rotacja: `docs/runbooks/backup-restore.md`).
- Zmiana ustawień LLM po starcie: w aplikacji (Ustawienia → Modele). Zmienne `WD_LLM_DEFAULT_*` służą tylko do zasiewu przy pierwszym uruchomieniu.
- Dev nie ma basic auth Traefika (SPA wysyła `Authorization: Bearer`, więc middleware by ją odrzucał); chroni go logowanie WD, rejestracja jest wyłączona.

## Rollback

W `platform-gitops` cofnij commit bota zmieniający `image.tag` (`git revert <sha> && git push`); Argo CD przywróci poprzednie obrazy
(Harbor trzyma 3 ostatnie `dev-*` i 5 `prod-*`). Migracje schematu nie są cofane: sprawdź, czy poprzednia wersja działa z nowym schematem.

## Diagnostyka

| Objaw | Gdzie patrzeć |
|---|---|
| Czerwony PR | zakładka *Checks* (job `image (backend)`, `image (web)`); lokalnie `docker build --target test backend` / `frontend` |
| `api` w `Init:Error` | `kubectl logs -n wawelsky-dragon-<env> deploy/wawelsky-dragon-api -c init` (migracje, połączenie z bazą) |
| `worker` czeka w init | `api` nie jest gotowe (`/health/ready`) |
| Brak wyników wyszukiwania internetowego | pod `searxng`; wynik pusty nie blokuje reszty |
