# Dziennik biegów harnessu `wdeval` (live)

Bieg: `tools/dev/live.sh eval <profil>` (TL, zespół A2, WP E1-10b). Ramię `fast`, `k = 1,3,6`, `top_n = 6`, `similarity_threshold = 0.2`.
Modele: czat `openai/gpt-4.1-mini`, embedding `openai/text-embedding-3-large` (3072). Sędzia: do E1-10b `openai/gpt-5.4` (bramka WD, `reasoning_effort = medium`),
**od E1-10c `glm-5.3-flash` przez OpenRouter (dostawca z.ai bez fallbacków, `WD_JUDGE_*`, `reasoning.effort = medium`, `temperature = 0`) — ten sam sędzia co w becie** (Q2).

**Sędzia gpt-5.4 (biegi z E1-10b, wiersze poniżej) — nieporównywalny z betą.** Była to ta sama rodzina co czat (decyzja właściciela Q2 = b; klucz bramki miał dostęp tylko do `openai/*`); metryki sędziego
(`answer_correct`, grounded, empty_ok, citation_ok) z tych wierszy są nieporównywalne z betą. Od E1-10c sędzia = beta (wiersz „nightly, sędzia glm-5.3-flash”); metryki retrievalu (`fragment_recall`, `doc_recall`) od sędziego nie zależą.
Manifest starszych artefaktów podaje rodzinę sędziego `unknown`; artefakt E1-10c: `judge_model = {name: glm-5.3-flash, family: zhipu-glm, mode: medium, endpoint: judge_env}`.

## Biegi

| data | profil | commit | czas biegu | pozycje (beta / codex-gold / poquad; pl / en) | answer_correct | fragment_recall @1 / @3 / @6 | doc_recall @1 / @3 / @6 | grounded | empty_ok | citation_ok | parse_miss sędziego |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 2026-09-29 | dev #1 (`20260929T003440Z`) | `3619dbb` | 1613 s (zasiew 60 s) | 227 (17 / 10 / 200; 223 / 4) | 135/179 | 149 / 163 / 165 z 227 | 166 / 172 / 174 | 157/179 | 7/48 | 185/217 | 10 |
| 2026-09-29 | dev #2 (`20260929T010142Z`) | `3619dbb` | 1666 s (zasiew 62 s) | 227 (jak wyżej) | 134/179 | 149 / 163 / 165 z 227 | 166 / 172 / 174 | 161/179 | 7/48 | 184/218 | 10 |
| 2026-09-29 | nightly (`20260929T014154Z`) | `640cf67` | 2613 s (zasiew 636 s) | 244 (29 / 15 / 200; 239 / 5) | 148/196 | 153 / 169 / 174 z 244 | 171 / 183 / 186 | 173/196 | 10/48 | 192/233 | 15 |
| 2026-09-29 | nightly, sędzia glm-5.3-flash (`20260929T072227Z`, E1-10c) | `3e8ff04` | ok. 41 min (zasiew 656 s) | 244 (29 / 15 / 200; 239 / 5) | 147/196 | 153 / 169 / 174 z 244 | 171 / 183 / 186 | 186/196 | 12/48 | 212/233 | 15 |

Bieg nightly #1 (kod `3619dbb`) padł po 633 s: `TimeoutError` przy zasiewie (limit 600 s na ramię przekroczony przez duże PDF-y; `SeedTimeout` był przykryty `TimeoutError` z zatrzymania workera).
Poprawka w `wdeval` (limit 2400 s, raport oczekujących dokumentów co 120 s, worker nie maskuje wyjątku) → bieg #2. Łącznie **4 biegi live** (limit Q2 = 4).

Rozbicie per źródło (trafienia `fragment_recall@6` / pozycje z określonym recall; `answer_correct` / pozycje answerable):

| bieg | beta | codex-gold | poquad |
|---|---|---|---|
| dev #1 / #2 | frag@6 12/17, answer 12/17 | frag@6 2/10, answer 3/10 | frag@6 151/200, answer 120 / 119 z 200 |
| nightly | frag@6 22/29, answer 26/29 | frag@6 4/15, answer 3/15 | frag@6 148/200, answer 119/200 |

Zasiew nightly: 199 dokumentów, 8841 chunków, 2 dokumenty nieudane: `apple_2024_10k.html` (embedding: bramka odrzuca pusty string w wejściu — `input cannot be an empty string`, patrz „Uwagi”)
i `unctad2004.ppt` (`EmptyDocument`: stary `.ppt` zawiera tylko obrazy/OLE — 0 tekstu). Zasiew dev: 499 chunków, 193 dokumenty, 1 dokument nieudany (ten sam `apple_2024_10k.html`, ten sam błąd embeddingu).

Artefakty: `backend/wdeval/data/baseline/20260929-dev-live.json` (= bieg dev #1), `backend/wdeval/data/baseline/20260929-nightly-live.json`.

## Determinizm retrievalu (dev #1 vs dev #2)

- `fragment_recall` (@1/3/6) i `doc_recall`: **identyczne dla wszystkich 227 pozycji** (w tym 17 pozycji bety).
- `retrieved_chunks` (lista top-6): identyczna dla 222 z 227; różni się na 5 pozycjach (1 beta: `un-02`, 4 poquad: `poquad-0102-00-04`, `-0186-00-04`, `-1052-00-02`, `-1302-00-03`) — zmiana dotyczy ogona listy (pozycje 3–6, kolejność lub jeden chunk nie-relewantny), bez wpływu na recall. To znany dług: brak treściowego klucza wtórnego przy remisach score (`docs/modules/eval.md`, „Znane ograniczenia”; dług E2-1).
- Odpowiedzi LLM: tekst różny w 70 z 227 pozycji, `answer_correct` różne w 1 (poquad), grounded 157 vs 161 (n = 179 w obu), citation_ok n 217 vs 218. Wariancja sędziego/odpowiedzi rzędu 1–4 pozycji na 179–218 — raportowane, nie naprawiane.

## S3 — `fragment_recall@6` WD na pozycjach bety ≥ baseline bety

Metoda (wg briefu): referencja `backend/wdeval/data/beta/baseline/20260910.json`, `items` z `arm == "fast"`, `fragment_recall["6"]` (pomiń `None`); dla każdego `item_id` wpis `corpus == "full"`, jeśli istnieje,
inaczej `subset` → **29 pozycji, 22 trafienia (0,759)**. WD: `items` z `source == "beta"`, `arm == "fast"`, `fragment_recall["6"]` (pomiń `None`). Porównanie na wspólnym zbiorze `item_id`.

| bieg | wspólny zbiór | wynik | status |
|---|---|---|---|
| **nightly** (pełne S3) | 29 pozycji | **WD 22/29 vs beta 22/29** (0,759 vs 0,759) | S3 spełnione (WD ≥ beta) |
| dev #1 | 17 pozycji | WD 12/17 vs beta 12/17 | S3 częściowe, równo |
| dev #2 | 17 pozycji | WD 12/17 vs beta 12/17 | S3 częściowe, równo |

- WD przegrywa (beta trafia, WD nie): `tx-02` (w obu biegach dev i w nightly).
- WD wygrywa (WD trafia, beta nie): `nr-04` (w obu biegach dev i w nightly).
- Pozycje bety poza zbiorem dev (`ss-01…07`, `tf-01…05`) w nightly: WD i beta zgodnie 22/29 łącznie, bilans różnic ±1 jak wyżej.
- Wynik S3 nie zależy od sędziego (tylko retrieval). Decyzja Q3 (co robić przy S3 < beta) nie dotyczy — S3 nie jest poniżej bety.

## Język odpowiedzi

Heurystyka: dla pozycji `language == "pl"` z niepustą odpowiedzią — odpowiedź uznana za polską, jeśli zawiera polskie znaki diakrytyczne (`ąćęłńóśźż`) albo co najmniej 2 polskie słowa funkcyjne
(`jest, nie, się, w, na, z, do, oraz, który, która, że, to, przez, dla`).

| bieg | pozycje `pl` z odpowiedzią | odpowiedź po polsku |
|---|---|---|
| dev #1 | 223 | 223 (100%) |
| dev #2 | 223 | 223 (100%) |
| nightly | 239 | 239 (100%) |

Pozycje `en` (4 w dev, 5 w nightly): odpowiedzi po angielsku, z wyjątkiem jednej odmowy w formie stałego komunikatu po polsku (`Nie znalazłem odpowiedzi na to pytanie w dostępnych dokumentach.`).

## Uwagi

- **Sędzia — sensowność n na live:** liczebności n są sensowne (grounded 179–196, citation_ok 217–233, empty_ok 48), w odróżnieniu od fake (n ≤ 5). `parse_miss` sędziego 10 (dev) / 15 (nightly) to 4–6% werdyktów; nie są nigdzie ponawiane.
- **`empty_ok` 7/48 (dev), 10/48 (nightly):** model rzadko odmawia dla 48 pozycji bez odpowiedzi; odpowiedź „nie wiem” jest wymuszana stałym komunikatem tylko przy pustym retrievalu, a próg `similarity_threshold = 0.2` przepuszcza chunki. To obserwacja jakości RAG (poza zakresem WP), nie błąd harnessu.
- **`answer_correct` dla codex-gold 3/10 (dev) i 3/15 (nightly)** przy `fragment_recall@6` 2/10 i 4/15 — złoto Codex jest trudne (tabele/OCR/prezentacje) lub ma inne kryteria niż sędzia; nie analizowano przyczyn.
- **Sędzia `openai/gpt-5.4`:** bramka odrzuca dla tego modelu `temperature` przy `reasoning_effort` oraz `chat_template_kwargs` (400); harness dla modeli `openai/*` wysyła tylko `reasoning_effort`, bez `temperature`
  (`wdeval/judge.py`). Dla pozostałych sędziów (qwen/GLM) kształt wywołania bez zmian.
- **Błąd w `app/**` (nie naprawiany):** `apple_2024_10k.html` nie zaindeksował się w nightly — do bramki embeddingów trafia pusty string (`input[2]`: „input cannot be an empty string”), a `embed_texts` (`app/services/embed.py:52`,
  wywołanie z `app/services/ingest_pipeline.py:271`) go nie filtruje. Dotyczy dev i nightly (żadna pozycja bety/gold nie ma w top-6 chunków z tego pliku; wpływ na S3 nie wykryty).
- **`unctad2004.ppt`:** `catppt` zwraca pusty tekst (`app/parsing/converters/pptx.py:127`) — zachowanie zamierzone (`EmptyDocument`), plik jest w korpusie nightly bez tekstu do wyszukiwania.
- **Czas zasiewu nightly 636 s** przy 8841 chunkach (dominuje `gus_rocznik_statystyczny_rp_2024.pdf` i `projekt_ustawy_o_systemach_ai_2026.pdf`); stąd limit zasiewu 2400 s.
- **Koszt (szacunek, bez telemetrii tokenów w artefakcie):** pomiar próbny sędziego `gpt-5.4` (reasoning medium): 370–1120 tokenów wejścia i 30–200 tokenów wyjścia na werdykt. Przyjęto ~445 werdyktów na bieg dev,
  ~2000 tokenów wejścia i ~150 wyjścia na werdykt (2,50 USD / 15 USD za 1 mln), odpowiedzi `gpt-4.1-mini` ~3,5 tys. tokenów wejścia (0,40 / 1,60 USD) i embeddingi (0,13 USD) → dev ≈ 3,5–5 USD,
  nightly (244 pozycje + większy zasiew) ≈ 4–6 USD, poniżej progu 7 USD z briefu; nightly uruchomiono. Rzeczywiste koszty należy sprawdzić na koncie bramki.

## E1-10c — sędzia `glm-5.3-flash` (OpenRouter / z.ai) jak w becie

Bieg: `WD_EVAL_BETA_CORPUS=… WD_EVAL_CODEX_CORPUS=… tools/dev/live.sh eval nightly` → kod 0; artefakt `backend/wdeval/data/baseline/20260929-nightly-live-judge-glm.json` (`judge_model.endpoint = judge_env`, brak URL-a/klucza w artefakcie).
Sędzia: 196 werdyktów grounded, 233 citation_ok, 48 empty_ok (n > 0, brak `value: null`); `parse_miss` (agregat) 15 — jak w biegu gpt-5.4. Test live sędziego: `pytest-live tests/live/test_gateway_models.py` → 4 passed; odpowiedź OpenRouter niesie `provider = "Z.AI"`.

| metryka sędziego | nightly gpt-5.4 (E1-10b) | nightly glm-5.3-flash (E1-10c) | beta `20260910.json`, wspólne `item_id` (fast; `full` przed `subset`) |
|---|---|---|---|
| grounded | 173/196 | 186/196 | WD 22/27 vs beta 27/27 (27 wspólnych werdyktów) |
| empty_ok | 10/48 | 12/48 | WD 2/2 vs beta 2/2 |
| citation_ok | 192/233 | 212/233 | WD 3/3 vs beta 2/3 (beta oceniała cytowania tylko dla 3 pozycji) |

Uwagi: beta ma werdykty sędziego tylko dla 29 wspólnych pozycji (92 wpisy w 3 ramionach), więc porównanie na wspólnych `item_id` jest wąskie (grounded n = 27). Różnica grounded 22/27 vs 27/27 to obserwacja, nie bramka.
Zmiana sędziego z gpt-5.4 na glm-5.3-flash podniosła grounded z 88% do 95% i citation_ok z 82% do 91% na tych samych 244 pozycjach (retrieval `fragment_recall@6` = 174/244 bez zmian) (zmiana wynika ze zmiany sędziego, nie z retrievalu; nie oceniano, który sędzia jest trafniejszy).
S3 z nowego biegu (tylko do wiadomości): WD 22/29 vs beta 22/29 (retrieval bez zmian; nie jest bramką).
Koszt (szacunek): sędzia GLM 5.3 Flash ~ 470 werdyktów × ~2 tys. tokenów wejścia ≈ 1 mln tokenów wejścia + odpowiedzi czatu i embeddingi jak w E1-10b nightly (~4 USD) — łącznie kilka USD; rzeczywisty koszt na koncie OpenRouter/bramki.
Bieg za zgodą właściciela z 08:00 (Q2); pierwsza próba tej zmiany zakończyła się kodem 3 (brak plików korpusu w ścieżce bety — błąd środowiska wywołania, bez zasiewu i bez wywołań LLM).
