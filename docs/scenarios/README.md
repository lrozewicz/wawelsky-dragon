# Biblioteka scenariuszy użytkownika (regresja)

Każda usterka znaleziona przez właściciela (albo QA-UI w trybie „pierwszy użytkownik”) staje się tu scenariuszem
w formacie skilla `user-scenarios` i nie znika po zamknięciu WP. WP poprawkowy kopiuje potrzebne scenariusze do
`work/wp/<id>/SCENARIOS.md` (nadając im identyfikatory `SC-<WP>-NN` i zostawiając odsyłacz do `R-…`), a jego pierwsze
zadanie to test e2e czerwony przed poprawką.

| Plik | Obszar |
|---|---|
| [ingestia.md](ingestia.md) | upload, parsowanie, OCR/VLM, postęp, Stop, wydajność dużych dokumentów |
| [modele-i-konfiguracja.md](modele-i-konfiguracja.md) | dostawcy i modele, konfiguracja datasetu, znaczenie pól |
| [instalacja.md](instalacja.md) | czysta instalacja z `docker-compose.yml`, pierwsze logowanie, pierwszy dataset |
| [wyglad.md](wyglad.md) | układ, 390 px, długie dane (reguły U1–U10) |
| [czat-mapa-bazy.md](czat-mapa-bazy.md) | pytania o zawartość bazy, spis treści dokumentów (mapa bazy, K21/K22) |

Status scenariusza: `OTWARTY` (usterka nienaprawiona), `TEST` (jest test e2e — ścieżka), `ZAMKNIĘTY` (test zielony na `main`).
Źródła: `work/v1-usterki.md` (test v1, 2026-10-03), `work/INBOX-architect.md` (test Q34, 2026-10-05).
