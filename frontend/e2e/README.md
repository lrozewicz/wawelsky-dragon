# e2e (Playwright) — jak dodać scenariusz

Harness z briefu WP E3-2 (T1). `bun run e2e` stawia izolowany stos testowy (`tools/dev/up.sh
test`), seeduje bazę, uruchamia Playwright na kontenerze `web` i **zawsze** sprząta stos
(`tools/dev/up.sh test down`, także przy porażce i Ctrl-C).

## Struktura

- `run.sh` — orkiestracja: stos `mariadb-test migrate api web fake-llm`, oczekiwanie na
  `/health/ready`, eksport `WD_E2E_BASE_URL`/`WD_E2E_API_URL`, sprzątanie w `trap EXIT`.
  Kod wyjścia skryptu = kod Playwrighta.
- `../playwright.config.ts` — `testDir: './e2e'`, projekt `chromium` (Desktop Chrome),
  `workers: 1`, `retries: 0`, `screenshot: 'only-on-failure'`, `trace: 'retain-on-failure'`,
  artefakty w `frontend/test-results/` (gitignored).
- `global-setup.ts` — seed przed biegiem: `POST ${WD_E2E_API_URL}/api/wd/v1/test/reset` z `{}`
  (K9). Status ≠ 200 przerywa bieg z treścią odpowiedzi.
- `fixtures.ts` — `test`/`expect` z autofixture `page`: każdy błąd konsoli (`console.error`)
  i `pageerror` wywala test; `ADMIN_EMAIL`/`ADMIN_PASSWORD` (konto z seedu K9);
  `resetDb(request)` do ponownego seedu w trakcie scenariusza.

## Jak dodać scenariusz

1. Nowy plik `e2e/<nazwa>.spec.ts`; importuj `test`/`expect` **z `./fixtures`**, nie
   z `@playwright/test` — inaczej nie działa strażnik błędów konsoli.
2. Adres aplikacji to `use.baseURL` (`WD_E2E_BASE_URL`) — używaj ścieżek względnych
   (`page.goto('/login')`). API pod bezpośrednim adresem: `process.env.WD_E2E_API_URL`.
3. Logowanie i inne dane z seedu bierz z `ADMIN_EMAIL`/`ADMIN_PASSWORD`; stan zmieniający dane
   cofaj przez `resetDb(request)`.
4. Uruchom `bun run e2e` (albo `cd frontend && bunx playwright test --list` dla samej
   weryfikacji konfiguracji). Bieg zostawia stos wyłączony — nie uruchamiaj `run.sh`
   równolegle z `./.claude/verify.sh`, bo oba używają tego samego projektu stosu.

Scenariusze dziedziczą `locale: pl-PL` z `playwright.config.ts`. To celowe: aplikacja startuje
z językiem `navigator.language` (`i18n.ts` → `detectLanguage`), a język profilu dochodzi dopiero
z `GET /users/me` po zalogowaniu — bez `locale` etykiety zależałyby od domyślnego locale Chromium.
Scenariusze, które nie zakładają konkretnego języka, mogą go nadpisać per plik (`test.use`).

## Argumenty (`bun run e2e -- …`)

Wszystko po `--` `run.sh` przekazuje wprost do Playwrighta (`bunx playwright test "$@"`), więc
działają filtry plików, `--grep`, `--list` i pozostałe flagi CLI:

```
bun run e2e -- e2e/s04-chunks.spec.ts          # tylko ten plik
bun run e2e -- --grep "S6-01"                  # tylko testy pasujące do tytułu
bun run e2e                                    # cały zestaw
```

Bez argumentów `"$@"` rozwija się do pustej listy, więc zachowanie `bun run e2e` się nie zmienia.
Wyjątek: pierwszy argument `--sso` obsługuje sam harness (`bun run e2e:sso`) i kończy się kodem 3.

`typecheck` obejmuje też `e2e/**` i `playwright.config.ts` (projekt `tsconfig.e2e.json`,
`tsc --noEmit -p tsconfig.e2e.json`), więc błąd typu w scenariuszu wywala `bun run typecheck`.

## Adres stosu (WD_HOST)

Porty stosu publikuje demon Dockera na hoście. Z kontenera agenta Packhorse (bridge) `localhost`
tam nie prowadzi, dlatego `run.sh` liczy host tak samo jak `tools/dev/up.sh test env`:
`${WD_HOST:-host.docker.internal}` — i z niego buduje `WD_E2E_API_URL`, `WD_E2E_WEB_URL` oraz
adres pętli `/health/ready`. Poza kontenerem uruchom z `WD_HOST=localhost`.

`WD_E2E_API_URL`/`WD_E2E_WEB_URL` służą procesom Node (`global-setup`, fixture `request`, seed).
**Nawigacje i asercje stron** idą przez `use.baseURL` (`WD_E2E_BASE_URL`), który `run.sh` ustawia
na ten sam adres co `WD_E2E_WEB_URL`. Cookie `wd_refresh` ma flagę `Secure` tylko w prod
(`_cookie_secure`), a stos testowy startuje z `WD_ENV=test`, więc po HTTP sesja przeżywa F5 bez
obejścia `e2e.localhost`/`--host-resolver-rules` (K8, T-clean).

Scenariusz, który musi uderzyć w API bezpośrednio (nie przez proxy `web`), powinien użyć
`process.env.WD_E2E_API_URL` (absolutny URL).

## Filtr błędów konsoli (401 z odświeżania sesji)

Wejście na `/` bez sesji woła `POST /api/v1/auth/refresh`, który zwraca 401 — to oczekiwany
stan (08 §5.3), ale Chromium loguje każde nieudane żądanie sieciowe jako `console.error`
(„Failed to load resource: the server responded with a status of 401"). Fixture pomija
**wyłącznie** komunikaty, których `message.location().url` zawiera `/api/v1/auth/refresh`
i których treść zawiera `401`; każdy inny błąd konsoli wywala test.

## Przeglądarka

`@playwright/test` 1.63.0 wymaga Chromium w wersji 1243. Kontener Packhorse ustawia
`PLAYWRIGHT_BROWSERS_PATH=/opt/ms-playwright` (przeglądarki `playwright-cli`, katalog tylko do
odczytu i bez wersji 1243), dlatego `run.sh` wskazuje cache użytkownika
(`$HOME/.cache/ms-playwright`; można go nadpisać przez `WD_E2E_BROWSERS_PATH`). Instalacja:

```
PLAYWRIGHT_BROWSERS_PATH=~/.cache/ms-playwright bunx playwright install chromium
```

## axe

`@axe-core/playwright` **nie jest** zależnością projektu (`frontend/package.json`), więc
w scenariuszach nie ma asercji dostępności — dodanie zależności to wniosek do Architekta/TL
(08 §11.2 chce `axe` na kluczowych ekranach).

## Scenariusze

- `smoke.spec.ts` — stos odpowiada (`/healthz` web, `/health/ready` API), a SPA startuje bez
  błędów konsoli.
- `s01-login.spec.ts` (S6-01) — `/` bez sesji → `/login?redirect=…`; złe hasło → `login-error`;
  poprawne logowanie → baner `home-banner` i kolejność pozycji `nav.main` (Start, Bazy wiedzy,
  Czat, Wyszukiwanie, Pliki, Ustawienia, Administracja — bez flag `FEATURE_*` wypadają
  Agent/Pamięć, `Administracja` wchodzi dla admina z seedu, `Pomoc` wymaga `DOCS_URL`);
  F5 → sesja z cookie `wd_refresh`; wylogowanie z menu użytkownika → `/login`.
  `axe` na `/` i `/login` pominięty — brak zależności.
- `s02-dataset-create.spec.ts` (S6-02) — po `resetDb` login przez UI → `/datasets` z pustym
  stanem → „Utwórz dataset” (nazwa + domyślny embedding + General) → `/dataset/files/:id`
  z nagłówkiem datasetu → karta widoczna na liście i w sekcji baz wiedzy na Home.
- `s03-upload-parse.spec.ts` (S6-03) — baza wiedzy z API (`createDataset`) → `/dataset/files/:id`
  → „Prześlij plik” → trzy próbki z `e2e/fixtures` (`sample.pdf`, `sample.docx`, `sample.xlsx`) przez
  ukryty `upload-input` z włączonym „Parsuj po przesłaniu” → „Przesłano” dla każdej i zamknięcie
  dialogu → każdy wiersz dochodzi do chipa „Sukces” (timeout `POLL_TIMEOUT_MS`), a kolumna Chunki
  ma liczbę > 0.
- `s03b-upload-stop.spec.ts` (S6-03, akt drugi) — duży plik tekstowy (~3 MB) budowany w pamięci
  i wysyłany przez `setInputFiles({ name, mimeType, buffer })`; ⊗ (`status-stop-<id>`) pojawia się
  dopiero w stanie „W kolejce”/„Parsowanie”, więc scenariusz czeka na przycisk (`waitFor`), klika
  i oczekuje chipa „Anulowano”.
- `s06-dataset-config.spec.ts` (S6-06) — dataset ze sparsowanym dokumentem (API: `seedCorpus`)
  → `/dataset/configuration/:id`: pola „Zaawansowane” poza DOM do rozwinięcia akordeonu, model
  embeddingu zablokowany przy chunkach, zmiana metody na Q&A → potwierdzenie „Dokumenty
  wymagają ponownego parsowania” → F5 pokazuje metodę Q&A; drugi dataset bez dokumentów ma
  embedding odblokowany.
- `s07a-chats-list.spec.ts` (S7a) — pusty stan listy czatów → utworzenie czatu → `/chat/:id`
  z nagłówkiem → zębatka i zmiana opisu w szufladzie (zakładka „Asystent”) → F5 zachowuje opis →
  powrót na `/chats` → usunięcie czatu z menu karty → znowu pusty stan.
- `s07-chat-citations.spec.ts` (S6-07) — czat z bazą wiedzy (tworzoną przez API: upload i parse do
  `DONE`) i modelem `fake-chat-think` wybranym w szufladzie ustawień: sekcja „Myślenie…”,
  streamowana odpowiedź, chip cytowania z popoverem (nazwa dokumentu i podobieństwo) i szuflada
  podglądu dokumentu; drugi test: Stop przerywa stream (spowolnione wyłącznie przekazanie żądania
  do prawdziwego backendu).
- `s08-sessions.spec.ts` (S6-08) — czat i baza wiedzy przez API; pierwsze pytanie tworzy rozmowę
  o nazwie z pierwszych 50 znaków pytania, zmiana nazwy z menu, F5 na `?conversationId=`
  odtwarza historię z cytowaniem, usunięcie rozmowy z potwierdzeniem.
- `s17-kb-export.spec.ts` (SC-E7-2-01 + warianty, SC-E7-2-05; WP E7-2 T3) — eksport bazy wiedzy
  z menu ⋮: dialog z podsumowaniem i przełącznikiem „Dołącz wektory” (szacunek zmienia rozmiar),
  pasek zadań z procentem i „Gotowe · X MB · link ważny do”, pobranie paczki (nazwa i rozmiar
  z `ExportResult`), link bez sesji w nowym kontekście (schowek przez spy na `execCommand`,
  wzór s21), F5 trzyma wiersz w pasku. Warianty: 390 px, ciemny motyw, EN, długa nazwa (120
  znaków, ellipsis + tooltip). SC-E7-2-05: członek zespołu przy bazie `permission=team` nie ma
  „Eksportuj”, superuser przy cudzej bazie ma. Dane przez `helpers/kbTransfer.ts` (korpus GUS
  poza repo, zasiew raz na plik); testy czerwone na bazie bez implementacji UI (E7-2 faza 2).
- `s17b-kb-import.spec.ts` (SC-E7-2-02, -03, -04; WP E7-2 T3) — import paczki `.wdkb.zip`
  jako użytkownik B: drop `DataTransfer` z bajtami pobranymi w stronie z podpisanego linku
  (paczka ~74 MB nie przechodzi przez most CDP) i wariant `setInputFiles`, pasek wysyłania
  (spowolnione porcje — wzór s07), podsumowanie z „Zgodny z paczką”, koniec „Gotowe — 2 pliki”,
  „Otwórz” → pliki „Sukces” bez parsowania, czat z cytatem z rocznika; SC-E7-2-03: konflikt
  nazwy (409 `name_conflict` z propozycją) i model niezgodny (ponowny embedding), SC-E7-2-04:
  paczka z niezgodną sumą i `.txt` przemianowany na `.wdkb.zip` (budowane wg K19 §2), odcicie
  sieci na 5 s z „Wznawianie…”, Stop importu i eksportu. Oczekiwane błędy konsoli (409 startu,
  `net::ERR_` przy odciciu) przez `takeOverConsoleGuard` (wzór s11).
- `visual-kb-transfer.spec.ts` (WP E7-2 T7; wzorce zrzutow jak `visual.spec.ts`) — dialog eksportu,
  dialog importu (krok 1, krok 2 zgodny, krok 2 niezgodny model, lista błędów walidacji) i pasek
  zadań (w toku, gotowy eksport, gotowy import, błąd) — każdy wzorzec × wariant (jasny 1280,
  ciemny 1280, jasny 390). Stany wymuszone przez `page.route` na trasy K19 `/api/wd/v1/...`
  (odpowiedzi wg `docs/contracts/K19-eksport-import.md` §3) i zasiew `localStorage`
  `wd.kbTasks.v1:<userId>` (`addInitScript`; identyfikator aktora z `GET /users/me` w `beforeAll`)
  — wzorce NIE zależą od backendu K19. Dane stabilne (stałe liczby, daty, nazwy ASCII); wzorce
  aktualizuje się świadomie: `bun run e2e -- e2e/visual-kb-transfer.spec.ts --update-snapshots=all`,
  obejrzenie (Read) i commit. Logowanie: 27 logowań UI na bieg łamie limiter logowania backendu
  (10/min, CONTRACT E5-2a §4 — 429 „Too many login attempts"), dlatego sesję ustawia mock trasy
  `POST /api/v1/auth/refresh` z prawdziwym tokenem z seedu (`beforeAll`; jeden login na bieg).
- `helpers.ts` — wspólne funkcje API scenariuszy czatu i datasetów: logowanie przez UI i przez API,
  baza z dokumentem sparsowanym do `DONE` (`seedCorpus`), baza bez dokumentów (`createDataset`),
  tworzenie czatu.
- `helpers/kbTransfer.ts` — dane scenariuszy eksportu/importu (WP E7-2): zasiew bazy korpusową
  parą GUS+NCBR (ścieżki: `WD_REAL_CORPUS` albo `dataset/documents/pl` obok głównego checkoutu
  przez `git-common-dir`), eksport przez API + pobranie paczki bez aktora, odpytywanie zadań,
  import przez API (stan wyjściowy SC-E7-2-03), konta i modele embeddingów (sztafaż), budowa
  paczek uszkodzonych (K19 §2) i drop paczki z `DataTransfer` pobieranej w stronie.

## Próbki (`e2e/fixtures`)

Zacommitowane pliki binarne dla S6-03 — wszystkie < 200 kB, treść to kilka zdań po polsku o Wawelu
(ponad `min_chars = 150` parsera, więc powstaje co najmniej jeden chunk):

| Plik          | Rozmiar | Pochodzenie                                                                          |
| ------------- | ------- | ------------------------------------------------------------------------------------ |
| `sample.pdf`  | ~25 kB  | wygenerowany przez Chromium (`page.pdf()`); polskie znaki z osadzonym `ToUnicode`    |
| `sample.docx` | ~1,7 kB | wygenerowany skryptem `zipfile` (minimalny OOXML: `word/document.xml`)               |
| `sample.xlsx` | ~2,3 kB | ten sam skrypt (`xl/workbook.xml` + `xl/worksheets/sheet1.xml`, tekst w `inlineStr`) |

Próbki z `backend/tests/**` nie nadają się: jedyny PDF (`fixtures/parsing/encrypted.pdf`) jest
zaszyfrowany, a `tools/test-data/` jeszcze nie istnieje. `python-docx`/`openpyxl`/`reportlab` nie są
w środowisku agenta (brak `backend/.venv`, `uv` bez sieci), więc DOCX i XLSX powstają z biblioteki
standardowej, a PDF z Chromium Playwrighta (zależność dev repo). Generacja jest jednorazowa (pliki
są zacommitowane); DOCX/XLSX odtwarzają się bajtowo (stała data wpisów ZIP), PDF niesie datę
utworzenia Chromium, więc powtórka daje inne bajty przy tej samej treści.

DOCX i XLSX — `python3 gen_ooxml.py frontend/e2e/fixtures`:

```python
import sys, zipfile
from pathlib import Path

OUT = Path(sys.argv[1])
TITLE = "Zamek Królewski na Wawelu"
PARAGRAPHS = [
    "Zamek Królewski na Wawelu wznosi się na wzgórzu nad Wisłą w Krakowie i przez stulecia był siedzibą królów Polski.",
    "Najstarsze murowane budowle pochodzą z czasów Kazimierza Wielkiego, a renesansową przebudowę prowadzono za panowania Zygmunta Starego.",
    "W komnatach zamku można oglądać arrasy wawelskie, kolekcję porcelany oraz Szczerbiec, miecz koronacyjny królów Polski.",
    "Wzgórze wawelskie obejmuje także katedrę, krypty królewskie, Smoczą Jamę oraz wieżę Zygmunta z dzwonem z 1521 roku.",
]
ROWS = [
    ("Miejsce", "Rok", "Opis"),
    ("Zamek Królewski", "1504", "Renesansowa przebudowa za Zygmunta Starego"),
    ("Katedra wawelska", "1364", "Konsekracja katedry za Kazimierza Wielkiego"),
    ("Smocza Jama", "1595", "Legenda o smoku wawelskim pod wzgórzem"),
    ("Wieża Zygmunta", "1521", "Dzwon Zygmunt odlany przez Hansa Behema"),
]
CONTENT_TYPES = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
    '<Default Extension="xml" ContentType="application/xml"/>'
    '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
    '<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>'
    '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
    '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>\n'
)
ROOT_RELS = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
    '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/></Relationships>\n'
)
CORE = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
    '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/">'
    f"<dc:title>{TITLE}</dc:title><dc:creator>Wawelsky Dragon E2E</dc:creator></cp:coreProperties>\n"
)


def docx_document() -> str:
    body = "".join(
        f'<w:p><w:r><w:t xml:space="preserve">{text}</w:t></w:r></w:p>' for text in PARAGRAPHS
    )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body>{body}</w:body></w:document>\n"
    )


def xlsx_workbook() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<sheets><sheet name="Wawel" sheetId="1" r:id="rId1"/></sheets></workbook>\n'
    )


def xlsx_sheet() -> str:
    rows = []
    for index, row in enumerate(ROWS, start=1):
        cells = "".join(
            f'<c r="{chr(ord("A") + column)}{index}" t="inlineStr"><is>'
            f'<t xml:space="preserve">{value}</t></is></c>'
            for column, value in enumerate(row)
        )
        rows.append(f'<row r="{index}">{cells}</row>')
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f'<sheetData>{"".join(rows)}</sheetData></worksheet>\n'
    )


def put(archive: zipfile.ZipFile, name: str, data: str) -> None:
    """Wpis ZIP ze stałą datą — powtórka generacji daje identyczne bajty."""
    info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o644 << 16
    archive.writestr(info, data)


OUT.mkdir(parents=True, exist_ok=True)
with zipfile.ZipFile(OUT / "sample.docx", "w", zipfile.ZIP_DEFLATED) as archive:
    put(archive, "[Content_Types].xml", CONTENT_TYPES)
    put(archive, "_rels/.rels", ROOT_RELS)
    put(archive, "docProps/core.xml", CORE)
    put(archive, "word/document.xml", docx_document())
with zipfile.ZipFile(OUT / "sample.xlsx", "w", zipfile.ZIP_DEFLATED) as archive:
    put(archive, "[Content_Types].xml", CONTENT_TYPES)
    put(archive, "_rels/.rels", ROOT_RELS)
    put(archive, "docProps/core.xml", CORE)
    put(archive, "xl/workbook.xml", xlsx_workbook())
    put(
        archive,
        "xl/_rels/workbook.xml.rels",
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
        'Target="worksheets/sheet1.xml"/></Relationships>\n',
    )
    put(archive, "xl/worksheets/sheet1.xml", xlsx_sheet())
```

PDF — `node gen_pdf.cjs <katalog-docelowy>` z katalogu `frontend` (Chromium z `playwright-core`,
ścieżka przeglądarek z `$HOME/.cache/ms-playwright`):

```js
const { chromium } = require('playwright-core')
const out = process.argv[2]
const paragraphs = [
  'Zamek Królewski na Wawelu wznosi się na wzgórzu nad Wisłą w Krakowie i przez stulecia był siedzibą królów Polski.',
  'Najstarsze murowane budowle pochodzą z czasów Kazimierza Wielkiego, a renesansową przebudowę prowadzono za panowania Zygmunta Starego.',
  'W komnatach zamku można oglądać arrasy wawelskie, kolekcję porcelany oraz Szczerbiec, miecz koronacyjny królów Polski.',
  'Wzgórze wawelskie obejmuje także katedrę, krypty królewskie, Smoczą Jamę oraz wieżę Zygmunta z dzwonem z 1521 roku.',
]
const html = `<html lang="pl"><head><meta charset="utf-8"></head><body style="font-family: serif">
<h1>Zamek Królewski na Wawelu</h1>${paragraphs.map((text) => `<p>${text}</p>`).join('')}</body></html>`

async function main() {
  const browser = await chromium.launch({ args: ['--no-sandbox'] })
  const page = await browser.newPage()
  await page.setContent(html)
  await page.pdf({ path: `${out}/sample.pdf`, format: 'A4' })
  await browser.close()
}

void main()
```

Uruchomienie z katalogu `frontend` (skrypt tymczasowy, `node` rozwiązuje `playwright-core`
z `node_modules`):

```bash
PLAYWRIGHT_BROWSERS_PATH=$HOME/.cache/ms-playwright node gen_pdf.cjs e2e/fixtures
```

## Przeszkody środowiskowe rozwiązane w T1b

Blokowały `bun run e2e` przy pierwszym logowaniu; wszystkie zamknięte:

1. **CSP bez jawnego `script-src`** (`frontend/serve.ts`) — Chromium logował `error: Note that
'script-src' was not explicitly set…` przy modulepreload Vite. Dodane `script-src 'self'`
   (DEC-056); polityka skutecznie bez zmian, filtr w fixture nadal zabroniony (DEC-053 B).
2. **Cookie `wd_refresh` (`Secure`) poza `localhost`** — Chromium nie zapisywał cookie na
   `http://host.docker.internal`, więc F5 gubił sesję. Obejście w harnessie (`e2e.localhost` +
   `--host-resolver-rules`, DEC-054) zostało usunięte w T-clean (K8): backend nadaje flagę
   `Secure` tylko przy `env=prod` (`_cookie_secure`), a stos testowy działa z `WD_ENV=test`.
3. **Brak `WD_SECRET_KEY` w stosie testowym** — `POST /api/v1/auth/login` z poprawnym hasłem
   kończył się `code 100` (`jwt.exceptions.InvalidKeyError: HMAC key must not be empty`). Stała
   testowa, niesekretna (≥32 B) dodana do `&test-backend-env` w `docker-compose.test.yml` i do
   wyjścia `tools/dev/up.sh test env` — jak `WD_CRYPTO_KEY` (DEC-053 A).

## SSO

`bun run e2e:sso` = `run.sh --sso`. Brak `docker-compose.sso.yml`, więc harness kończy się
kodem 3 (BLOCKED) z komunikatem `S6-01b: tryb test nie obsługuje --sso`.
