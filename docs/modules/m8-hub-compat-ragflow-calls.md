# M8b — kontrakt RAGFlow dla hub-compat (stan po E2-5, 2026-09-29)

## Co robi
Testy kontraktu `backend/tests/contract/hub_compat/ragflow_calls/` odtwarzają wywołania R1–R7 klienta hub-compat (repozytorium prywatne)
(klient pisany pod RAGFlow v0.24; klucz z `compat_profile=ragflow_0_24`, konto serwisowe superuser) i sprawdzają pola, które hub-compat czyta.
Nagłówki jak w hub-compat: `Content-Type: application/json` także przy GET/DELETE (A9), R7 tylko `Authorization`. Jedyna zmiana kodu produkcyjnego
WP: domyślne sortowanie sesji v0.24 (A4, DEC-048). Reszta powierzchni RF działała już po E2-2/E2-2b.

## Publiczny interfejs
Brak nowych tras. Pliki testów (każdy z `pytestmark = [hub_compat, contract, db, fakellm]`):
- `conftest.py` — fixture'y `client, hub` (superuser + klucz 0.24), `stranger` (nie-superuser + klucz 0.24), `owner` (właściciel czatu), `hub_chat` (czat + dataset + dokument po ingestii), `reasoning_llm` (model `fake-chat-think`); pomocniki `hub_headers`, `doc_headers`, `ok_data`.
- `test_r1_r3_r4_sessions_chats.py`, `test_r2_sessions_history.py`, `test_r5_r6_completions.py`, `test_r7_document_download.py`, `test_chat_flow_ai_hub.py`.
Zmiana kodu: `app/api/ragflow/normalize/sessions.py::parse_session_list(query, profile, max_size)` — `_DEFAULT_ORDERBY` = `update_time` (0.24) / `create_time` (0.27); `routes/sessions.py::list_sessions` przekazuje profil.

## Jak uruchomić i przetestować
`cd backend && uv run --frozen pytest -q -m contract tests/contract/hub_compat/ragflow_calls` (stos `tools/dev/up.sh test`) → wszystkie zielone, 0 skip.
Mutacje: `tools/dev/mutation-check.sh backend/tests/mutations/e2-5-*.patch <test>` → „MUTACJA WYKRYTA” (R7 bez autoryzacji, R2 bez kontroli czatu, A4).

## Odstępstwa od docs/architecture/03-hub-compat.md
| punkt spec | co zrobiono | dlaczego |
|---|---|---|
| §8 A4 | sesje 0.24 domyślnie `update_time DESC`; jawne `orderby` wygrywa | DEC-048 |
| §3 R7 | `Content-Type: application/octet-stream` (profil 0.24, także dla `.txt`) i `Content-Disposition: attachment; filename*=UTF-8''<nazwa>` (proza: `filename=…`, typ wg rozszerzenia) | złoto v0.24.0 `documents_extras--28` wygrywa; proza 03 do poprawy przez Architekta |
| §3 R2 / AG-05 | referencje w historii bez `similarity` (7 kluczy) | upstream `list_session`; hub-compat ma `similarity?` opcjonalne (`types/ragflow.ts:52`); DEC-048 |
| §9 flow | czat scenariusza z `refine_multiturn: False` | fake-llm nie przepisuje pytania wieloturowego; DEC-049 |

## Znane ograniczenia i dług
- `refine` w wieloturze nie jest pokryty pod fake-llm (DEC-049).
- `refusals_v024.py::documents_download_missing_document` (złoto `errors_access--47`) jest nieosiągalne: trasa pobrania zawsze używa klucza `documents_download`, więc komunikat dla nieistniejącego dokumentu różni się od złota (kod `102`, koperta JSON — AG-28 spełnione; hub-compat sprawdza tylko `res.ok`).
- Odmowy nie-superusera: `102` (`You do not own the dataset …`, `You don't own the assistant …`, `You don't own the chat …`) wg złota v0.24.0.
- Testy dodane w E2-5 nie uruchamiają żywego hub-compat (E4-7).

## Historia
| WP | data | zmiana |
|---|---|---|
| E2-5 | 2026-09-29 | Testy kontraktu R1–R7 (AG-01…AG-08, AG-28, `test_chat_flow_ai_hub`), A4 (DEC-048), DEC-049 |
