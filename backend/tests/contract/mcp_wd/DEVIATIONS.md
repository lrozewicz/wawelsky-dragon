# Odchyłki testu kontraktowego MCP (T5, K17 §5)

Testy `backend/tests/contract/mcp_wd/` porównują serwer MCP WD ze złotem
`backend/tests/contract/golden/v0.27.2/mcp/*.json` (oba transporty, kroki 06–33).
Złoto nagrał WP E6-0 na stosie **upstream RAGFlow v0.27.2** (korpus „smokwawelski”,
dataset `wd_rec_e6_mcp_ds`, czat `wd_rec_e6_mcp_chat`); testy uruchamiane są na stosie **WD**
z korpusem konta testowego (dataset `wd_sc_e6_2_ds_a`, czat `wd_sc_e6_2_chat`). Stąd świadome
rozróżnienia między „kontraktem protokołu” (porównywany dosłownie) a „danymi korpusowymi”
(porównywane strukturalnie). Reguły realizuje `golden_compare.py`.

## Świadome odchyłki od złota

| Pole / zachowanie | Powód | Kontrakt |
|---|---|---|
| `result.capabilities.experimental` = `{}` (oba transporty) | WD **nie odbija nagłówków żądania** do `experimental.headers` (upstream robi to w `handle_sse` — wyciek klucza API) | K17 §2, CONTRACT WP E6-2 |
| `result.serverInfo.version` (`1.30.0` vs złote `1.28.1`) | wersja zainstalowanego pakietu `mcp`; porównanie ze złotem: pole **maskowane** | K17 §2 |
| `result.content.*.text.chunks.*.positions` | `positions` zależą od parsera dokumentu (korpus recordera vs korpus testowy: `[[1,0,0,0,0]]` vs `[]`), nie od warstwy MCP | K17 §4 (kształt jak złoto, bez pozycji) |

`positions` to jedyna różnica **strukturalna** (długość listy) między korpusem recordera a WD;
pozostałe pola korpusowe (nazwy, treści, `similarity`, liczniki) mają ten sam **typ** i przechodzą
porównanie typowe.

## Maskowanie (nie-odchyłki — reguły porównania)

- **Id-ki**: liść złota w formie tokenu (`<ID:…>`, `<FLOAT>`, `<DATETIME>`, `<IGNORE>`) — strona
  realna musi być tokenem (normalizacja kodem recordera: `normalize.py` + `IdRegistry`); numery
  tokenów (i rodzaje, np. `<ID:document#1>` vs `<ID:id#1>`) **nie** są porównywane.
- **Opisy narzędzi** (`ragflow_retrieval`/`ragflow_list_datasets`/`ragflow_list_chats`):
  porównywane po **podstawieniu listy zasobów konta testowego** — prefiks do pierwszego `{`
  musi być identyczny, a doklejona lista musi mieć zgodną liczbę wpisów i zbiory kluczy
  (`id`/`name`/`description`); nazwy i id zasobów są korpusowe (golden-E6 „Uwagi ogólne”).
- **Teksty błędów narzędzi** (`Tool not found: …`, `Input validation error: …`) i pola
  `error_type`/`http_status`/`protocolVersion`/`serverInfo.name`/nazwy narzędzi/`inputSchema`
  — porównywane **dosłownie** (niezależne od korpusu).
- **`result.message`** kroków auth: sprawdzany udział „Unauthorized” (URL w komunikacie zawiera
  host/port stosu, więc nie porównujemy bajt w bajt) — K17 §3.3–3.4.
