# Scenariusze regresji — czysta instalacja i pierwszy użytkownik

Stos: prod (`docker-compose.yml`, `--build`, `.env` z `scripts/gen-secrets.sh`), bez `test/reset`.
Wyrocznia: krok `clean-install` w `verify-full` (`frontend/e2e-real/clean-install.spec.ts`).

## R-INS-01: Pierwsze logowanie i pierwszy dataset — TEST (E5-H1; usterki #1, #2)
| # | Krok | Oczekiwany wynik |
|---|---|---|
| 1 | `docker compose up -d --build --wait` na świeżym klonie | `/health/ready` 200; `migrate` zakończony, admin utworzony z `WD_ADMIN_*` |
| 2 | Loguje się kontem z `WD_ADMIN_*` | Home z banerem powitalnym |
| 3 | Tworzy dataset domyślnym modelem embeddingów | dataset utworzony bez ręcznej konfiguracji (wymiar wykryty automatycznie) |
| 4 | Wgrywa i parsuje 1 dokument | „Sukces”; retrieval zwraca trafienie |

## R-INS-02: Sesja po HTTP — TEST (E5-H6b; U1)
| # | Krok | Oczekiwany wynik |
|---|---|---|
| 1 | Instalacja bez TLS (`http://host:8080`), logowanie, F5 | sesja przeżywa odświeżenie (cookie bez `Secure` przy `WD_COOKIE_SECURE=false`) |

## R-INS-03: Instrukcja właściciela krok po kroku — QA-UI „pierwszy użytkownik”
Przy zamknięciu każdego etapu z UI QA-UI przechodzi `work/v1-test-wlasciciela.md` od zera i zapisuje każdą rozbieżność
instrukcja ↔ rzeczywistość oraz każde miejsce, w którym nie wiedział, co zrobić (`qa-ui.md` krok 5).

## R-INS-04: Podłączenie klienta MCP do Wawelskiego Smoka — ZAIMPLEMENTOWANY (E6-2, K17; testy: `tools/dev/mcp-prod-check.sh`, `frontend/e2e/s20-mcp-card.spec.ts`)
Persona: użytkownik z kluczem API chce, by Claude Desktop/Cursor przeszukiwał jego bazy; administrator włącza serwer.
| # | Krok | Oczekiwany wynik |
|---|---|---|
| 1 | Admin: `docker compose --profile mcp up -d` (runbook §13) | usługa `mcp` zdrowa ≤ 30 s; reszta stosu bez restartu |
| 2 | Użytkownik: Ustawienia → Klucze API → karta „Serwer MCP” → kopiuje przykład konfiguracji, wstawia swój klucz | adres w przykładzie = adres, pod którym otworzył WD (przez `web:8080`, bez dodatkowego portu) |
| 3 | Klient MCP łączy się (`/mcp`, potem `/sse`) i wywołuje `ragflow_list_datasets`, `ragflow_retrieval` z pytaniem po polsku | widzi tylko swoje datasety; fragmenty z jego dokumentów |
| 4 | Zły klucz / brak klucza | brak klucza: 401 z czytelnym `error`; zły klucz: błąd z „Unauthorized” przy liście narzędzi |
| 5 | Serwer wyłączony (bez profilu), klient łączy się | 503 `MCP server is not enabled (compose profile "mcp")` — nie strona SPA ani 502 |
