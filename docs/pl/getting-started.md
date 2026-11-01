# Pierwsze kroki

[English](../en/getting-started.md)

## Wymagania

- Docker Engine z Compose v2 na Linuksie x86-64.
- Co najmniej 16 GB RAM i 50 GB dysku przy domyślnych limitach (MariaDB 8 GB, worker 4 GB, API 1 GB, web, wyszukiwarka i MCP po 256 MB).
- Bramka zgodna z OpenAI do czatu i embeddingów (np. LiteLLM). Rerank jest opcjonalny.

## Dobór zasobów

Pula InnoDB powinna mieć co najmniej 1,3 × rozmiar tabel wektorów i chunków, bo każde zapytanie skanuje wektory wybranych baz wiedzy.

| Chunki skanowane jednym zapytaniem | Wymiar | Dane | Pula InnoDB | Limit kontenera |
| --- | --- | --- | --- | --- |
| do 20 000 | 3072 | ok. 0,4 GB | 1 GB | 2 GB (wariant minimalny) |
| 100 000 | 1024 | ok. 1,0 GB | 2 GB | 4 GB |
| 100 000 | 3072 | ok. 1,9 GB | 6 GB (domyślnie) | 8 GB (domyślnie) |
| 300 000 | 3072 | ok. 5,7 GB | nie mieści się w 8 GB | potrzeba więcej RAM lub partycjonowania |

Na mniejszym serwerze ustaw `WD_MARIADB_MEMORY=2g` i `WD_MARIADB_BUFFER_POOL=1G`. Ten wariant nadaje się do około 20 000 chunków: przy 100 000 chunków wymiaru 3072 każde zapytanie czyta z dysku, a p95 rośnie z ok. 1,3 s do ok. 7,7 s ([pomiary](../perf/E5-1b.md)).

## Instalacja

Wszystkie polecenia uruchamiaj w katalogu głównym repozytorium.

1. Wygeneruj sekrety. Skrypt tworzy `.env` z `.env.example` z prawami `0600` i bez `--force` nie nadpisze istniejącego pliku.

   ```bash
   scripts/gen-secrets.sh
   ```

2. Uzupełnij `.env`:
   - `WD_LLM_BASE_URL` i `WD_LLM_API_KEY`: bramka LLM;
   - `WD_ADMIN_EMAIL` i `WD_ADMIN_PASSWORD`: konto administratora, zakładane raz, przy pierwszym starcie;
   - opcjonalnie: `WD_PUBLIC_BASE_URL`, `WD_HTTP_PORT` (domyślnie 8080), `WD_OIDC_*` (logowanie SSO).

3. Uruchom stos. `--build` jest potrzebne przy pierwszym starcie i po aktualizacji, inaczej użyty zostanie istniejący obraz.

   ```bash
   docker compose up -d --build --wait
   ```

4. Sprawdź działanie:

   ```bash
   docker compose ps
   curl -fsS http://localhost:8080/healthz              # web działa i widzi API
   curl -fsS http://localhost:8080/health/ready         # baza osiągalna, schemat aktualny
   curl -fsS http://localhost:8080/api/v1/system/healthz
   ```

5. Otwórz http://localhost:8080 i zaloguj się. Dodaj bazę wiedzy, wgraj i sparsuj dokumenty, a potem utwórz asystenta czatu.

Logi i zatrzymanie:

```bash
docker compose logs -f api worker
docker compose down
```

TLS nie jest częścią stosu: przed usługą `web` postaw reverse proxy albo ingress.

## Co dalej

[Runbook administratora](../runbooks/admin.md) opisuje dostawców modeli, Keycloak/OIDC, klucze API, SharePoint, OCR, MCP, kopie zapasowe, aktualizacje i migrację z RAGFlow.

## Testy

Każdy obraz ma etap budowania `test`, ten sam, który uruchamia CI:

```bash
docker build --target test backend
docker build --target test frontend
```
