# Wawelsky Dragon — dokumentacja

| Dokument | Faza | Zawartość |
|---|---|---|
| [01-analiza-ragflow.md](01-analiza-ragflow.md) | 1 | architektura RAGFlow v0.27.2, przepływy danych, ranking błędów, co zachować/wyrzucić, kontekst hub-compat, wnioski z bety |
| [ARCHITECTURE.md](ARCHITECTURE.md) | 2 | **Big Picture**: cele, zakres, decyzje (ADR-01…20), stos, moduły, etapy, otwarte decyzje |
| [architecture/01-backend-rdzen.md](architecture/01-backend-rdzen.md) | 2 | M1 — układ backendu, DI, konfiguracja, błędy, logi, konwencje |
| [architecture/02-api.md](architecture/02-api.md) | 2 | M7 — API zgodne z RAGFlow (v0.27 + shim v0.24), OpenAI, Dify, rozszerzenia WD |
| [architecture/03-hub-compat.md](architecture/03-hub-compat.md) | 2 | M8 — kontrakt hub-compat, user-api, migracja danych z RAGFlow |
| [architecture/04-dane-mariadb.md](architecture/04-dane-mariadb.md) | 2 | M2 — schemat, wektory, FULLTEXT, migracje |
| [architecture/05-ingestion.md](architecture/05-ingestion.md) | 2 | M4+M5 — LLM, kolejka, worker, parsery, chunker, embeddingi |
| [architecture/06-retrieval-chat.md](architecture/06-retrieval-chat.md) | 2 | M6 — retrieval, czat, cytowania, SSE, search app |
| [architecture/07-auth-uzytkownicy.md](architecture/07-auth-uzytkownicy.md) | 2 | M3 — logowanie, OIDC, klucze API, polityka dostępu |
| [architecture/08-frontend.md](architecture/08-frontend.md) | 2 | M10 — SPA na MUI z IA RAGFlow, strony, formularze, scenariusze UI |
| [architecture/09-integracje-sharepoint.md](architecture/09-integracje-sharepoint.md) | 2 | M9 — framework konektorów, SharePoint |
| [architecture/10-testy-jakosc.md](architecture/10-testy-jakosc.md) | 2 | M11 — strategia testów, pokrycie ≥80%, e2e, eval, **lista plików testowych** |
| [architecture/11-infrastruktura.md](architecture/11-infrastruktura.md) | 2 | M12 — Docker Compose, obrazy, env, backup, bezpieczeństwo |
| [architecture/12-plan-realizacji.md](architecture/12-plan-realizacji.md) | 2→3 | etapy E0–E6, pakiety pracy dla 2 zespołów, spike'i |
| [02-flow-agentow.md](02-flow-agentow.md) | 3 | flow zespołu agentów w Claude Code (role, modele D13, hooki); konfiguracja w `.claude/` |
| [03-spike-s0-wyniki.md](03-spike-s0-wyniki.md) | 3 | **wyniki spike'a S0** (weryfikacja flow agentów na zabawkowym repo), znalezione błędy i poprawki, checklista przed E0 |
| [BIG-PICTURE.md](BIG-PICTURE.md) | 5 | co realnie powstało: moduły, przepływy, odchyłki od specyfikacji (odsyłacze do modułów i DEC) |
| [runbooks/admin.md](runbooks/admin.md) | 5 | runbook administratora: pierwsze uruchomienie, dostawcy modeli, OIDC/Keycloak, klucze API, SharePoint, backup/restore, aktualizacja, migracja i przepięcie hub-compat |
| [runbooks/backup-restore.md](runbooks/backup-restore.md) | 5 | kopia zapasowa (B1), odtworzenie i rotacja `WD_CRYPTO_KEY` |
| (poza repozytorium publicznym) | — | dokumentacja przepięcia klienta hub-compat — część prywatna |
