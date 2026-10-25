# Pochodzenie fragmentów z RAGFlow — inwentaryzacja (WP E5-5, Q22)

Cel: wskazać, które fragmenty Wawelskiego Smoka (WD) są **faktycznie skopiowane lub zaadaptowane** z RAGFlow
(InfiniFlow, Apache-2.0), tak by `NOTICE` ([../../NOTICE](../../NOTICE)) opisywał je precyzyjnie, a reszta pozostała
oryginalnym kodem WD. Zgodność z API RAGFlow (trasy, kody błędów, nazwy pól, komunikaty odtworzone z dokumentacji
i złota) **nie jest** przeniesieniem i nie wchodzi do inwentaryzacji.

Metoda: kandydaci z `grep -rniE 'ragflow|upstream|port(ed)? from|infiniflow'` w `backend/ frontend/src tools/ scripts/ deploy/`
i z dokumentów modułów/DEC; **każda pozycja potwierdzona** porównaniem z plikiem upstream
(`git -C ../ragflow show <tag>:<ścieżka>` na `v0.27.2` lub `v0.24.0`), nie z pamięci. Komentarz „port upstream” w kodzie WD
sam w sobie niczego nie dowodzi — sprawdzano zbieżność struktury kodu.

Szczegółowe tabele (ścieżka WD → plik upstream:linie → charakter → dowód podobieństwa → rozmiar → trudność):

- [parts/core.md](parts/core.md) — prompty, domena (czat, chunkowanie, retrieval), parsowanie, front: **29 pozycji, 3 wątpliwe**.
- [parts/api-tests.md](parts/api-tests.md) — warstwa API, usługi, testy upstream, złoto, narzędzia: **13 pozycji, 3 wątpliwe**.
- poniżej, sekcja „MCP (E6-2)”: port serwera MCP z upstream `mcp/server/server.py`: **2 pozycje**.

## MCP (E6-2) — port serwera upstream
Port z `mcp/server/server.py` upstream v0.27.2 (kontrakt `docs/contracts/K17-mcp.md`); WD rozbija go na dwa pliki:
`server.py` (aplikacja Starlette + narzędzia) i `client.py` (klient HTTP API WD). Porównania wykonano
`git -C <klon ragflow> show v0.27.2:mcp/server/server.py`.

| # | Ścieżka WD | Upstream (tag:ścieżka:linie) | Charakter | Dowód podobieństwa (porównanie) | Dowód w repo | Rozmiar WD (linie) | Trudność przepisania |
|---|---|---|---|---|---|---|---|
| mcp 1 | `backend/app/mcp/server.py` | `v0.27.2:mcp/server/server.py:452-518,546-665,716-804` | port logiki | ta sama klasa kontekstu (`ApiCtx` ≈ `RAGFlowCtx`), ta sama stała `AUTH_TOKEN_STATE_KEY = "ragflow_auth_token"`; przeniesione 1:1 `_extract_token_from_request` (`request.state` → nagłówki) i `_extract_token_from_headers` (kolejność Bearer → `api_key`/`x-api-key`) oraz ten sam komunikat `{"error": "Missing or invalid authorization header"}` z kodem 401; schematy i opisy trzech narzędzi dosłownie z upstream (`ragflow_retrieval`/`ragflow_list_datasets`/`ragflow_list_chats`); ta sama para tras `/sse` + `/messages/` i `/mcp` (`stateless=True`, `json_response=True`) | komentarz atrybucji w nagłówku pliku; `docs/contracts/K17-mcp.md` §2/§4; `docs/modules/m11-mcp.md` | 381 | średnia — port dużego pliku z odchyleniami (bez cache, `experimental` = `{}`) |
| mcp 2 | `backend/app/mcp/client.py` | `v0.27.2:mcp/server/server.py:58-450` (`RAGFlowConnector`) | port logiki | ta sama stała `_REST_API_MAX_PAGE_SIZE = 100`; te same `_get`/`_post` z nagłówkiem `Authorization: Bearer …` i `httpx.Timeout(60.0)`; ta sama sekwencja `list_datasets`/`list_chats`/`retrieval` i mapowanie pól chunku (`dataset_name`, `document_name`, `document_metadata`) oraz ich wartości domyślnych | komentarz atrybucji w nagłówku pliku; testy `backend/tests/contract/mcp_wd/**` | 359 | średnia |

Świadome różnice wobec upstreamu (nie kopiowane): brak cache metadanych i parametru `version` (`base_url` + `/api/v1`
na sztywno), brak odbijania nagłówków żądania w `initialize` (upstream to robi — wyciek klucza API, K17 §2),
brak trybu `self-host` (`WD_MCP_HOST_API_KEY`).

## Pozycje wątpliwe (do decyzji właściciela) — NA GÓRZE

Decyzja „wchodzi / nie wchodzi do `NOTICE`”. Obecny `NOTICE` ujmuje wyłącznie POZYCJE; wątpliwe poniżej nie są w nim wymienione.

| ID | Pozycja | Dlaczego wątpliwe |
|---|---|---|
| core W1 | `backend/app/core/error_codes.py` (`RetCode`, 16 linii) vs `common/constants.py:45-61` | Skopiowany enum nazw i wartości, ale to jednocześnie **interfejs API** (kody muszą się zgadzać). Rekomendacja: traktować jako zgodność API (poza `NOTICE`), ewentualnie dopisać komentarz atrybucji. |
| core W2 | `backend/app/domain/chunking/special.py` (presety presentation/one/table/stopki, ~340 linii) vs `rag/app/{presentation,one,table,paper}.py` | Zbieżność częściowa; pełny `diff` funkcja-po-funkcji niewykonany, WD ma inne wejście (bloki). Potwierdzony tylko `_qa_cells` (poz. 19). |
| core W3 | `backend/app/domain/retrieval/query.py` (68 linii) vs `rag/nlp/term_weight.py` | Formuła wagi terminu nie występuje w sprawdzanych plikach upstream — prawdopodobnie własna. |
| api W1 | `tools/contract-recorder/rf_bootstrap.py` (351 linii) vs `test/testcases/conftest.py` | Zbieżna sekwencja tras (zgodność), kod napisany niezależnie. Plik w rezerwacji E6-0. |
| api W2 | `backend/tests/contract/upstream/conftest.py` (958 linii) vs `test/testcases/conftest.py:21-336` | Plik własny WD (~95% inny), wspólny tylko pomysł stubów (~66 linii kontekstowych). |
| api W3 | `backend/app/services/documents_extra.py` (`_apply_updates/_apply_deletes`, ~25 linii) vs `doc_metadata_service.py:1271-1345` | Uproszczony wariant algorytmu z poz. 8 (api); zbieżność częściowa. |

Sprawa uboczna (poza RAGFlow): trafienia „upstream” w `frontend/src/theme/ColorModeSelect.tsx`, `hooks/useDialogs/**`, `theme/themePrimitives.ts`
dotyczą MUI/Toolpad (MIT), nie RAGFlow — mają własne komentarze atrybucji; `NOTICE` wymienia je w sekcji
„MUI i Toolpad (MIT)” ([../../NOTICE](../../NOTICE)).

## Aktualizacja E5-7 (2026-10-13): prompty własnymi słowami

Pozycje core 1-7 (8 plików `backend/app/prompts/*.md` oraz `KEYWORD_PROMPT`/`QUESTION_PROMPT` w `enrich.py`), 11 (domyślny prompt czatu),
23 (`search/config.py` — zmieniono tylko opis), 28 (`defaultPrompt.ts`), 30 i 31 (`meta_data.md`, `meta_filter.md`) zostały
przepisane własnymi słowami (nowa struktura i sformułowania, własne przykłady; zachowano jedynie zmienne szablonów, formaty wyjścia
parsowane przez kod i zdanie rozpoznawane `The answer you are looking for is not found in the dataset!`). Nie są już wymieniane
w `NOTICE`. Tabele powyżej i w `parts/core.md` opisują stan sprzed E5-7 (historia). Pozostaje poz. 29 (`schema.ts`, lista języków)
oraz porty logiki (poz. 8-10, 12-27), w tym parsery w `enrich.py`.

## Podsumowanie per kategoria

Rozmiary = linie plików WD objętych pozycją (górne oszacowanie; przy fragmentach pliku — rozmiar fragmentu, jeśli podano).

| Kategoria | Pozycje (core/api) | Rozmiar WD (linie) | Trudność przepisania | Uwagi dla decyzji o przepisaniu |
|---|---|---|---|---|
| Prompty i teksty domyślne (kopie) | core 1-7, 11, 23, 28, 29, 30, 31 | ~560 | niska | Same teksty promptów/konfiguracji — przepisanie to redakcja treści; 8 plików `backend/app/prompts/*.md` (w tym `meta_data.md`, poz. 30, i `meta_filter.md`, poz. 31) ma nagłówek InfiniFlow i różni się od upstream tylko tym nagłówkiem. Najtańsza droga do zmniejszenia `NOTICE`. |
| Porty logiki — czat/cytowania/prompt/chunkowanie/retrieval | core 8-10, 12-18, 20-22, 24, 27 | ~2400 (całe pliki; porty są ich częścią) | średnia (poz. 17 `naive_merge`: wysoka) | Najtrudniejsze: scalanie bloków (`general.py`), cytowania post-hoc (`citations.py`), budowa promptu. Przepisanie wymaga własnej specyfikacji zachowania + testów. |
| Porty logiki — drobne (regexy, konfiguracje, scalanie `parser_config`) | core 19, 25, 26 | ~40 | niska | Kilka–kilkanaście linii każdy. |
| Porty logiki — warstwa API (walidacja, pliki, MIME, metadane) | api 5-13 | ~880 (fragmenty) | niska–średnia | `CONTENT_TYPE_MAP` (40 par), `duplicate_name`, modele walidacji `parser_config`/`datasets`; walidacja zgodności API wymusza te same komunikaty, więc przepisanie ogranicza się do struktury kodu. |
| Testy przeniesione z upstream (kopie) | api 1-2 | 25 029 (`.py`) / 25 598 (z `.md/.toml`) | wysoka | 94 z 102 plików **identyczne bajt w bajt** (23 887 linii); zmodyfikowany `configs.py`. Przepisanie = napisanie własnego zestawu testów kontraktowych HTTP/SDK. Alternatywa: nie przepisywać, zostawić nagłówki i wpis w `NOTICE`. |
| Dane nagrane z upstream | api 3 | 371 plików JSON/SSE, 2,1 MB | niska | Odpowiedzi API nagrane z oficjalnych obrazów (dane, nie kod); można nagrać ponownie. Rezerwacja E6-0. |
| Konfiguracja stosu referencyjnego | api 4 | 163 + 178 linii | niska–średnia | `compose` recordera przepisany z upstream `docker/`; używany tylko do nagrań. Rezerwacja E6-0. |
| Port serwera MCP (E6-2) | mcp 1-2 | 740 | średnia | `mcp/server/server.py` → `backend/app/mcp/{server,client}.py`; odchyłki celowe: brak cache metadanych, brak odbijania nagłówków w `initialize`, brak trybu `self-host` (K17). |

## Elementy sprawdzone i odrzucone (bez wpisu w NOTICE)

Pełne listy w sekcjach ODRZUCONE obu części. Najważniejsze: reszta `backend/app/api/ragflow/**` i `backend/app/services/**`
(komentarze „upstream” dotyczą zgodności API), `backend/app/db/repositories/**`, `backend/app/parsing/**` (OTSL i parsowanie
własne), `backend/app/text/**`, `backend/app/domain/policy/**`, `retrieval/{stopwords,highlight}.py`, fuzja RRF (mechanizm
własny WD, brak w upstream), `backend/wdeval/**` (pochodzi z repozytorium bety WD, nie z RAGFlow), `tools/migrate-from-ragflow/**`,
`deploy/**`, `docker-compose*.yml`, `scripts/**`, `tools/{fake-llm,fake-graph,spikes}/**`, front (`splitThink.ts`, `reducer.ts` — własne).

## Znane ograniczenia weryfikacji

- Prompty core 2-6 potwierdzono zbiorczym pomiarem (każdy `diff` = dokładnie 4 linie nagłówka), nie osobną lekturą.
  Poz. 30 (`meta_data.md`, E6-1a) sprawdzono osobnym `diff` przeciw `v0.27.2:rag/prompts/meta_data.md` — 4 linie nagłówka, reszta bajt w bajt.
  Poz. 31 (`meta_filter.md`, E6-1a) sprawdzono osobnym `diff` przeciw `v0.27.2:rag/prompts/meta_filter.md` — 4 linie nagłówka, reszta bajt w bajt.
- Niektóre porty (core W2/W3, front) potwierdzano fragmentami/negatywnym grepem, nie pełnym `diff` funkcja-po-funkcji — stąd WĄTPLIWE.
- `v0.24.0`: porównania prowadzono głównie na `v0.27.2`; przy poz. dotyczących `v0.24.0` (compose recordera, komunikaty `/sessions/ask`) wskazano tag w tabelach.
- Atrybucję (komentarz w kodzie) dodano w 6 plikach, w których jej brakowało: `domain/chat/{config,think}.py`, `domain/chunking/{general,finalize}.py`,
  `llm/think.py` (zmiany wyłącznie komentarzy) oraz poprawiono błędny zakres linii w docstringu `domain/retrieval/scoring.py`.
  Pliki z rezerwacji (trafienie w katalogu klienta hub-compat, `golden/**`, `contract-recorder/**`, README, pliki E5-H8z) pozostawiono bez zmian — mają tylko wpis tutaj.
