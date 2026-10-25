// Wyrocznia realna: ingest całego korpusu PL przez UI na stosie produkcyjnym z nakładką fake-llm
// (CONTRACT WP E5-H5 §4.1.1 + §5 + §10, brief T2a/T2b). Test 1 „ingest”: logowanie formularzem,
// dataset domyślnym modelem, upload plików korpusu (chooser + prawdziwy drag & drop), parsowanie
// każdego do stanu końcowego zgodnego z `corpus-expectations.ts` i raport JSON. Test 2 „ui”:
// widok chunków jednego dokumentu, test retrievalu, czat z asystentem na datasecie → odpowiedź
// z przypisem cytowania i modal (rola `dialog`) z pełnym fragmentem w viewporcie. Kontrakt §4
// wymaga trybu serial (test 2 pracuje na datasecie testu 1). Zmienna WD_REAL_ONLY (filtr
// deweloperski) zawęża upload do plików pasujących regexem — wyrocznia końcowa biegnie bez niej.
import { mkdirSync, readdirSync, readFileSync, statSync, writeFileSync } from 'node:fs'
import { basename, extname, join } from 'node:path'
import type { Locator, Page } from '@playwright/test'

import { expect, test } from '@playwright/test'

import { BINARY_MISSING_PATTERN, ERROR_PATTERN, EXPECTED, MIN_CHUNKS } from './corpus-expectations'
import { dropFile } from './helpers/dnd'

const ADMIN_EMAIL = process.env.WD_CI_ADMIN_EMAIL ?? ''
const ADMIN_PASSWORD = process.env.WD_CI_ADMIN_PASSWORD ?? ''
const CORPUS = process.env.WD_REAL_CORPUS
const OUT = process.env.WD_REAL_OUT ?? ''

const DATASET_NAME = 'Real corpus'
// Filtr deweloperski (brief T2b p. 2): regex po nazwie pliku; brak = cały korpus. Służy WYŁĄCZNIE
// szybkiej iteracji (test „ingest” wgrywa tylko pasujące pliki) — wyrocznia końcowa bez niego.
const ONLY = process.env.WD_REAL_ONLY
// Dokument preferowany w teście „ui” (mały, tekstowy — z jego treści bierzemy pytanie).
const PREFERRED_DOC = 'fixture_rag_strukturalny.md'
const CHAT_NAME = 'Real chat'
// Prompt systemowy z placeholderem `{knowledge}` — bez niego walidacja blokuje zapis bazy wiedzy
// (chat.settings.systemKnowledge w locale pl / frontend/src/features/chats/settings/schema.ts).
const SYSTEM_PROMPT = 'Odpowiadaj na podstawie przekazanej wiedzy.\n\n{knowledge}'
// Viewport jak w e2e S6-07 (DESKTOP Chrome) — asercja „fragment w całości w viewporcie”.
const VIEWPORT = { width: 1280, height: 800 }
// Licznik chunków nagłówka panelu: „1 chunk” / „2 chunki” / „5 chunków” (locale chunks.json).
const CHUNK_TOTAL = /^\d+ chunk/
// Rozszerzenia, z których umiemy wyłuskać pytanie (dekodowalny tekst w UTF-8).
const TEXT_EXTS = new Set(['md', 'txt', 'csv', 'html', 'htm', 'eml'])
// Per plik: GUS 23 MB parsuje się ~745 s (BRIEF WP E5-H5); limit per plik 1200 s, cały test 1500 s.
const PER_FILE_TIMEOUT_MS = 1_200_000
const UPLOAD_TIMEOUT_MS = 300_000
// Czas na pojawienie się wiersza dokumentu w siatce po uploadzie (grid odświeża się co 3 s).
const ROW_TIMEOUT_MS = 60_000
// Plik ≥ 12 MB nie idzie przez `DataTransfer` (base64 w moście Playwrighta); zawsze przez chooser.
const BIG_FILE_BYTES = 12 * 1024 * 1024

// Stany końcowe kolumny „Status” (locale `frontend/src/locales/pl/datasets.json`).
const TERMINAL_STATUS = /^(Sukces|Błąd|Anulowano)$/
// Stan pozycji listy dialogu, gdy upload pliku został odrzucony (locale datasets.files.upload.error).
const UPLOAD_ERROR_TEXT = 'Błąd przesyłania'

type UploadPath = 'chooser' | 'dnd'

type CorpusFile = {
  name: string
  path: string
  ext: string
  bytes: number
  uploadPath: UploadPath
}

type DocResult = {
  name: string
  bytes: number
  status: string
  parse_seconds: number
  chunks: number
  path: UploadPath
}

/** Kolejność dokumentów w raporcie = kolejność korpusu; `results` wypełniane po nazwie. */
let corpusNames: string[] = []
const results: Record<string, DocResult> = {}

/** Rozszerzenie → MIME dla `File` w drag & drop. Backend rozpoznaje format po magic bytes. */
const MIME_BY_EXT: Record<string, string> = {
  pdf: 'application/pdf',
  txt: 'text/plain',
  md: 'text/markdown',
  csv: 'text/csv',
  html: 'text/html',
  eml: 'message/rfc822',
  jpg: 'image/jpeg',
  png: 'image/png',
  doc: 'application/msword',
  docx: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  xls: 'application/vnd.ms-excel',
  xlsx: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  pptx: 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
}

function mimeFor(name: string): string {
  return MIME_BY_EXT[extname(name).slice(1).toLowerCase()] ?? 'application/octet-stream'
}

/** Rekurencyjny zbiór ścieżek plików pod `dir`. */
function walk(dir: string, acc: string[]): void {
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const full = join(dir, entry.name)
    if (entry.isDirectory()) walk(full, acc)
    else if (entry.isFile()) acc.push(full)
  }
}

/**
 * Lista plików korpusu posortowana po pełnej ścieżce. Brak `WD_REAL_CORPUS` → wyjątek.
 * Podział: parzysty indeks w posortowanej liście → chooser, nieparzysty → dnd (CONTRACT §4);
 * plik ≥ 12 MB zawsze chooser (za duży na base64 w moście). W tym korpusie GUS (22 MB, indeks 8)
 * jest parzysty, więc obie reguły dają chooser; „lalka…” (indeks 13) idzie przez dnd.
 * `WD_REAL_ONLY` (regex po nazwie pliku) zawęża listę — filtr deweloperski, nie na wyroczni.
 */
function listCorpusFiles(): CorpusFile[] {
  if (CORPUS === undefined || CORPUS === '') {
    throw new Error('WD_REAL_CORPUS nie ustawione — uruchom przez tools/dev/clean-install.sh')
  }
  const paths: string[] = []
  walk(CORPUS, paths)
  paths.sort((a, b) => (a < b ? -1 : a > b ? 1 : 0))
  const only = ONLY === undefined || ONLY === '' ? null : new RegExp(ONLY)
  const selected = only === null ? paths : paths.filter((path) => only.test(basename(path)))
  return selected.map((path, index) => {
    const name = basename(path)
    const ext = extname(name).slice(1).toLowerCase()
    if (!(ext in EXPECTED)) {
      throw new Error(
        `korpus: nieznane rozszerzenie „.${ext}” (${name}) — uzupełnij corpus-expectations.ts`,
      )
    }
    const bytes = statSync(path).size
    const uploadPath: UploadPath = bytes >= BIG_FILE_BYTES || index % 2 === 0 ? 'chooser' : 'dnd'
    return { name, path, ext, bytes, uploadPath }
  })
}

/** Wiersz siatki dokumentu o danej nazwie (`role=row`; nazwa jest linkiem kolumny „Nazwa”). */
function documentRow(page: Page, name: string) {
  return page.getByRole('row').filter({ hasText: name })
}

/**
 * Czy dokument w ogóle powstał (wiersz w siatce). Pliki o nieobsługiwanym formacie backend
 * odrzuca już przy uploadzie (`UnsupportedFileType` → envelope code 500, „…has not been supported
 * yet!”), więc taki plik NIE ma wiersza — odróżniamy to od błędu parsowania.
 */
async function documentUploaded(page: Page, name: string): Promise<boolean> {
  try {
    await documentRow(page, name).waitFor({ state: 'visible', timeout: ROW_TIMEOUT_MS })
    return true
  } catch {
    return false
  }
}

/**
 * Powód stanu dokumentu: klik w chip statusu — jak użytkownik — otwiera dialog „Log parsowania”
 * z całym `progress_msg` (m.in. linia `[ERROR] …`); zwraca ten tekst. Dokument musi już mieć wiersz
 * i stan końcowy (używane wyłącznie dla plików, które się wgrały).
 */
async function readParseReason(page: Page, name: string): Promise<string> {
  const row = documentRow(page, name)
  await row.getByRole('button', { name: TERMINAL_STATUS }).click()
  const logDialog = page.getByRole('dialog')
  await expect(logDialog.getByRole('heading', { name: `Log parsowania — ${name}` })).toBeVisible()
  const reason = await logDialog.locator('pre').innerText()
  await logDialog.getByRole('button', { name: 'Zamknij' }).click()
  await expect(logDialog).toBeHidden()
  return reason.replace(/\s+/g, ' ').trim()
}

/** Wypełnia i wysyła formularz logowania na bieżącej stronie `/login` (bez wejścia na adres). */
async function submitLoginForm(page: Page): Promise<void> {
  await page.getByLabel('E-mail').fill(ADMIN_EMAIL)
  // `exact` — inaczej `getByLabel('Hasło')` trafia też w przycisk „Pokaż hasło” (aria-label z prefiksem).
  await page.getByLabel('Hasło', { exact: true }).fill(ADMIN_PASSWORD)
  await page.getByRole('button', { name: 'Zaloguj się' }).click()
}

/** Logowanie formularzem `/login` kontem administracyjnym czystej instalacji (wzorzec clean-install). */
async function loginAsAdmin(page: Page): Promise<void> {
  await page.goto('/login')
  await submitLoginForm(page)
  await expect(
    page.getByRole('navigation').getByRole('link', { name: 'Bazy wiedzy' }),
  ).toBeVisible()
}

/**
 * Wymaga, by cały element mieścił się w viewporcie (kontrakt WP E5-H3 §Plan testów e2e, jak
 * `frontend/e2e/s07-chat-citations.spec.ts`): `x/y ≥ 0` oraz `x+width/y+height ≤` wymiarów okna.
 */
async function expectInsideViewport(page: Page, locator: Locator, what: string): Promise<void> {
  const box = await locator.boundingBox()
  const viewport = page.viewportSize()
  expect(viewport, 'viewport').not.toBeNull()
  expect(box, `${what}: boundingBox`).not.toBeNull()
  expect(
    box!.x >= 0 &&
      box!.y >= 0 &&
      box!.x + box!.width <= viewport!.width &&
      box!.y + box!.height <= viewport!.height,
    `${what}: ${JSON.stringify(box)} w viewporcie ${viewport!.width}×${viewport!.height}`,
  ).toBe(true)
}

/** Ścieżka pliku o danej nazwie w korpusie (`WD_REAL_CORPUS`); brak pliku → wyjątek. */
function corpusPath(name: string): string {
  if (CORPUS === undefined || CORPUS === '') {
    throw new Error('WD_REAL_CORPUS nie ustawione — uruchom przez tools/dev/clean-install.sh')
  }
  const paths: string[] = []
  walk(CORPUS, paths)
  const hit = paths.find((path) => basename(path) === name)
  if (hit === undefined) throw new Error(`korpus: brak pliku ${name} pod ${CORPUS}`)
  return hit
}

/** Pierwsze zdanie pierwszego akapitu treści (po front-matter i nagłówkach) — brief T2b §3b. */
function firstSentence(text: string): string {
  const lines = text.split('\n')
  let start = 0
  if (lines[0]?.trim() === '---') {
    const end = lines.indexOf('---', 1)
    if (end > 0) start = end + 1
  }
  for (const raw of lines.slice(start)) {
    const line = raw.trim()
    if (line === '' || line.startsWith('#')) continue
    return line.split(/(?<=[.!?])\s+/)[0]?.trim() ?? ''
  }
  return ''
}

/**
 * Pytanie testu retrievalu i czatu: pierwsze zdanie treści dokumentu z korpusu. fake-embed jest
 * deterministyczny, więc pytanie dosłownie z chunku daje trafienie. Dla pliku binarnego nie ma
 * z czego wziąć pytania — wtedy uruchom z `WD_REAL_ONLY=<plik tekstowy>`.
 */
function corpusQuestion(name: string, ext: string): string {
  if (!TEXT_EXTS.has(ext)) {
    throw new Error(
      `ui: nie umiem wziąć pytania z pliku .${ext} — zawęź korpus filtrem WD_REAL_ONLY do pliku tekstowego`,
    )
  }
  return firstSentence(readFileSync(corpusPath(name), 'utf8'))
}

// Test 2 („ui”) pracuje na datasecie utworzonym przez test 1; serial wymusza kolejność.
test.describe.configure({ mode: 'serial' })

// Raport zapisujemy także, gdy asercje padły — TL ma dane przy czerwieni (CONTRACT §2).
test.afterAll(() => {
  const docs = corpusNames
    .map((name) => results[name])
    .filter((doc): doc is DocResult => doc !== undefined)
  if (OUT === '') return
  mkdirSync(OUT, { recursive: true })
  writeFileSync(`${OUT}/real-corpus.json`, `${JSON.stringify({ docs }, null, 2)}\n`)
})

test('ingest: logowanie, dataset, upload i parsowanie całego korpusu, raport', async ({ page }) => {
  test.setTimeout(1_500_000)

  const files = listCorpusFiles()
  corpusNames = files.map((file) => file.name)
  expect(files.length, 'liczba plików korpusu').toBeGreaterThan(0)

  // 1. Logowanie formularzem `/login` (selektory jak `clean-install.spec.ts`).
  await loginAsAdmin(page)
  const nav = page.getByRole('navigation')

  // 2. Dataset „Real corpus” domyślnym modelem (pola nie ruszamy — jak clean-install).
  await nav.getByRole('link', { name: 'Bazy wiedzy' }).click()
  await expect(page).toHaveURL(/\/datasets$/)
  await page.getByRole('button', { name: 'Utwórz dataset' }).first().click()
  const createDialog = page.getByRole('dialog')
  await expect(createDialog).toBeVisible()
  await createDialog.getByLabel('Nazwa').fill(DATASET_NAME)
  await createDialog.getByRole('button', { name: 'Utwórz' }).click()
  await expect(page.getByRole('heading', { name: DATASET_NAME })).toBeVisible()

  // 3. Dialog „Prześlij pliki” z włączonym „Parsuj po przesłaniu”.
  await page.getByRole('button', { name: 'Prześlij plik' }).click()
  const uploadDialog = page.getByRole('dialog')
  await expect(uploadDialog.getByRole('heading', { name: 'Prześlij pliki' })).toBeVisible()
  await expect(uploadDialog.getByRole('switch', { name: 'Parsuj po przesłaniu' })).toBeChecked()
  // Strefa drag & drop ma tekst „Przeciągnij pliki tutaj” — trafiamy tekstem (bez `data-testid`).
  // Zdarzenia na tym elemencie bąbelkują do `onDrop` strefy (Rodzic Box), więc `dropFile` działa.
  const dropzone = uploadDialog.getByText('Przeciągnij pliki tutaj')

  // 4a. Pliki „chooser” — jedno wywołanie okna wyboru z całą listą ścieżek.
  const chooserFiles = files.filter((file) => file.uploadPath === 'chooser')
  if (chooserFiles.length > 0) {
    const chooser = page.waitForEvent('filechooser')
    await uploadDialog.getByRole('button', { name: 'Wybierz pliki' }).click()
    await (await chooser).setFiles(chooserFiles.map((file) => file.path))
  }

  // 4b. Pliki „dnd” — po jednym, prawdziwym `DataTransfer` (base64), i kontrola, że trafiły na listę.
  for (const file of files.filter((entry) => entry.uploadPath === 'dnd')) {
    await dropFile(page, dropzone, readFileSync(file.path), file.name, mimeFor(file.name))
    await expect(uploadDialog.getByText(file.name, { exact: true })).toBeVisible()
  }

  // 5. Wysyłka. Czekamy, aż KAŻDA pozycja listy będzie w stanie końcowym: „Przesłano” albo
  //    „Błąd przesyłania” (nieobsługiwany format jest odrzucany już przy uploadzie — patrz
  //    `corpus-expectations.ts`). Nie zakładamy z góry, że wszystkie 16 wejdzie. Liczymy
  //    etykiety per plik z `exact: true` — od SC-E5-H9-03 po zakończeniu dochodzi jeszcze
  //    podsumowanie „Przesłano N z M”, które bez `exact` trafiłoby do licznika.
  const uploadedAt = Date.now()
  await uploadDialog.getByRole('button', { name: 'Prześlij' }).click()
  await expect
    .poll(
      async () =>
        (await uploadDialog.getByText('Przesłano', { exact: true }).count()) +
        (await uploadDialog.getByText(UPLOAD_ERROR_TEXT).count()),
      { timeout: UPLOAD_TIMEOUT_MS },
    )
    .toBe(files.length)
  // Przycisk znów aktywny = `start()` doszedł do końca (uploady + żądanie parsowania + odświeżenie listy).
  await expect(uploadDialog.getByRole('button', { name: 'Prześlij' })).toBeEnabled({
    timeout: UPLOAD_TIMEOUT_MS,
  })
  // Usterka UX z §10 zamknięta w T1 (WP E5-H6a §C1): odrzucony format pokazuje POD nazwą pliku
  // przyczynę z koperty API. Od V12-2 T3b UI tłumaczy ją na PL („Nieobsługiwany typ pliku:
  // witaminy_c_i_d.odp”); surowy tekst serwera nie może przejść przez tłumaczenie 1:1.
  if (files.some((file) => file.ext === 'odp')) {
    await expect(uploadDialog.getByText(/Nieobsługiwany typ pliku: .+\.odp/)).toBeVisible()
  }
  await uploadDialog.getByRole('button', { name: 'Gotowe' }).click()
  await expect(uploadDialog).toBeHidden()

  // 5b. Siatka domyślnie pokazuje 10 wierszy na stronę (paginacja serwerowa) — ustawiamy 50, żeby
  //     wszystkie wiersze korpusu było w DOM i dało się je obserwować równolegle.
  await page.getByRole('combobox', { name: /Wierszy na stronę/ }).click()
  await page.getByRole('option', { name: '50' }).click()

  // 6. Każdy dokument do stanu końcowego. `parse_seconds` to przybliżenie: od kliknięcia „Prześlij”
  //    do chwili zaobserwowania stanu końcowego (wszystkie parsują się równolegle na workerze).
  //    Plik odrzucony przy uploadzie nie ma wiersza — zapisujemy stan z dialogu i `chunks: -1`.
  await Promise.all(
    files.map(async (file) => {
      const elapsed = Math.round((Date.now() - uploadedAt) / 100) / 10
      if (!(await documentUploaded(page, file.name))) {
        results[file.name] = {
          name: file.name,
          bytes: file.bytes,
          status: UPLOAD_ERROR_TEXT,
          parse_seconds: elapsed,
          chunks: -1,
          path: file.uploadPath,
        }
        return
      }
      const row = documentRow(page, file.name)
      const statusButton = row.getByRole('button', { name: TERMINAL_STATUS })
      await expect(statusButton, `stan dokumentu ${file.name}`).toHaveText(TERMINAL_STATUS, {
        timeout: PER_FILE_TIMEOUT_MS,
      })
      const status = (await statusButton.innerText()).trim()
      // Kolumna „Chunki” DataGrid (MUI X) — atrybut `data-field`, nie `data-testid`; `formatNumber`
      // wstawia separator tysięcy (spacja), więc usuwamy białe znaki. Parser nieudany → 0.
      const chunkText = (await row.locator('[data-field="chunk_count"]').innerText()).replace(
        /\s/g,
        '',
      )
      const chunks = Number(chunkText)
      results[file.name] = {
        name: file.name,
        bytes: file.bytes,
        status,
        parse_seconds: Math.round((Date.now() - uploadedAt) / 100) / 10,
        chunks: Number.isNaN(chunks) ? -1 : chunks,
        path: file.uploadPath,
      }
    }),
  )

  // 7. Oczekiwania wg tabeli (CONTRACT §5 + §10). `expect.soft` — jeden bieg raportuje WSZYSTKIE
  //    niezgodności, nie tylko pierwszą (to wyrocznia usterkowa; nie ukrywamy). Rozszerzenie spoza
  //    tabeli odsialiśmy już w `listCorpusFiles`. Przy niezgodności dołączamy log parsowania do komunikatu.
  for (const file of files) {
    const result = results[file.name]
    const expected = EXPECTED[file.ext]

    // §10: `.doc`/`.ppt` w domyślnym workerze (bez OCR/wv) może paść na brak binarki — akceptujemy
    // „Sukces” albo „Błąd” z przyczyną pasującą do `BINARY_MISSING_PATTERN`; inny błąd = czerwono.
    if (expected === 'success-or-readable-error') {
      if (result?.status === 'Sukces') continue
      const reason = await readParseReason(page, file.name)
      expect.soft(result?.status, `status ${file.name} — log: ${reason}`).toBe('Błąd')
      expect.soft(reason, `status ${file.name} — log: ${reason}`).toMatch(BINARY_MISSING_PATTERN)
      continue
    }

    // readable-error: w UI musi być WIDOCZNY powód pasujący do ERROR_PATTERN. Gdy backend odrzucił
    // plik już przy uploadzie, wiersza w siatce nie ma — przyczynę z koperty (T1, WP E5-H6a §C1)
    // sprawdza twarda asercja przy wysyłce (krok 5), więc tutaj nie ma czego parsować.
    if (expected === 'readable-error') {
      if (result?.status === UPLOAD_ERROR_TEXT) continue
      const reason = await readParseReason(page, file.name)
      expect.soft(result?.status, `status ${file.name} — log: ${reason}`).toBe('Błąd')
      expect.soft(reason, `USTERKA: nieczytelny błąd dla ${file.name}`).toMatch(ERROR_PATTERN)
      continue
    }

    if (result?.status === 'Sukces') {
      // T4 (WP E5-H6d): próg minimalnej liczby chunków dla plików z `MIN_CHUNKS` (mapa pomiarowa).
      const min = MIN_CHUNKS[file.name]
      if (min !== undefined) {
        expect.soft(result.chunks, `chunki ${file.name}`).toBeGreaterThanOrEqual(min)
      }
      continue
    }
    const reason = await readParseReason(page, file.name)
    expect.soft(result?.status, `status ${file.name} — log: ${reason}`).toBe('Sukces')
  }
})

// Test 2 „ui” (brief T2b §3): użytkownik ogląda chunki jednego dokumentu, robi test retrievalu,
// tworzy asystenta na datasecie „Real corpus” i rozmawia z nim — odpowiedź niesie przypis
// cytowania, a jego klik otwiera modal z pełnym fragmentem. Logowanie NOWE (stan strony testu 1
// nie jest dziedziczony); dataset znajdujemy w UI po nazwie. Selektory: role/etykiety/tekst.
test('ui: chunki, test retrievalu, czat z cytowaniem i modal z fragmentem', async ({ page }) => {
  test.setTimeout(900_000)
  await page.setViewportSize(VIEWPORT)

  // 0. Dokument testu i pytanie z jego treści (brief §3a/§3b): preferowany md, a gdy filtr
  //    deweloperski go wykluczył — pierwszy wgrany dokument o oczekiwaniu „success”.
  const files = listCorpusFiles()
  const target =
    files.find((file) => file.name === PREFERRED_DOC) ??
    files.find((file) => EXPECTED[file.ext] === 'success')
  expect(target, `dokument do testu ui (wgranych plików: ${files.length})`).toBeDefined()
  const targetName = target!.name
  const question = corpusQuestion(targetName, target!.ext)
  expect(question.length, 'pytanie z treści dokumentu').toBeGreaterThan(0)

  // 1. Logowanie formularzem i wejście w dataset kartą listy (nazwa z briefu).
  await loginAsAdmin(page)
  const nav = page.getByRole('navigation')
  await nav.getByRole('link', { name: 'Bazy wiedzy' }).click()
  await expect(page).toHaveURL(/\/datasets$/)
  // Karta datasetu nawiguje teraz routerem (kontrakt WP E5-H6a §C2) — bez przeładowania dokumentu,
  // więc sesja nie przepada po HTTP i workaround z ponownym logowaniem (DEC-054) jest zbędny.
  await page.getByRole('link', { name: DATASET_NAME }).click()
  await expect(page).toHaveURL(/\/dataset\/files\//)
  await expect(page.getByRole('button', { name: 'Prześlij plik' })).toBeVisible({
    timeout: ROW_TIMEOUT_MS,
  })
  // Siatka domyślnie pokazuje 10 wierszy na stronę — 50, żeby docelowy wiersz był w DOM (jak test 1).
  await page.getByRole('combobox', { name: /Wierszy na stronę/ }).click()
  await page.getByRole('option', { name: '50' }).click()

  // 2. Widok chunków: nazwa dokumentu w kolumnie „Nazwa” jest linkiem do `/chunk/parsed/chunks`.
  await page.getByRole('link', { name: targetName, exact: true }).click()
  await expect(page).toHaveURL(/\/chunk\/parsed\/chunks/)
  await expect(page.getByRole('heading', { name: 'Wynik chunkowania' })).toBeVisible({
    timeout: ROW_TIMEOUT_MS,
  })
  // Najpierw czekamy na pierwszy wiersz chunku, bo spinner licznika pokazuje „0” zanim lista
  // się załaduje — dopiero potem odczyt liczby chunków ma sens (T7).
  await expect(page.getByLabel('Zaznacz chunk').first()).toBeVisible({ timeout: ROW_TIMEOUT_MS })
  const totalChunks = page.getByText(CHUNK_TOTAL).first()
  await expect(totalChunks).toHaveText(/[1-9]\d*/)
  const chunkCount = Number((await totalChunks.innerText()).replace(/\D/g, ''))
  expect(chunkCount, `liczba chunków ${targetName}`).toBeGreaterThan(0)

  // 3. Test retrievalu na tym samym datasecie: pytanie dosłownie z treści dokumentu (fake-embed
  //    jest deterministyczny) → co najmniej jedno trafienie („Łącznie N”, wzór clean-install.spec.ts).
  await page.getByRole('button', { name: 'Wstecz' }).click()
  await expect(page).toHaveURL(/\/dataset\/files\//)
  await page.getByRole('tab', { name: 'Test retrievalu' }).click()
  await expect(page).toHaveURL(/\/dataset\/retrieval\//)
  await page.getByLabel('Pytanie').fill(question)
  await page.getByRole('button', { name: 'Uruchom' }).click()
  const total = page.getByText(/Łącznie \d+/)
  await expect(total).toBeVisible({ timeout: 60_000 })
  const hits = Number((await total.innerText()).replace(/\D/g, ''))
  expect(hits, 'liczba trafień testu retrievalu').toBeGreaterThanOrEqual(1)

  // 4. Asystent „Real chat” na datasecie (model domyślny stosu) + prompt systemowy z `{knowledge}`.
  await nav.getByRole('link', { name: 'Czat' }).click()
  await expect(page).toHaveURL(/\/chats$/)
  await page.getByRole('button', { name: 'Utwórz czat' }).first().click()
  const createChat = page.getByRole('dialog')
  await createChat.getByLabel('Nazwa').fill(CHAT_NAME)
  await createChat.getByRole('button', { name: 'Utwórz' }).click()
  await expect(page).toHaveURL(/\/chat\/[^/]+$/)
  await page.getByRole('button', { name: 'Ustawienia czatu' }).click()
  await page.getByRole('tab', { name: 'Asystent' }).click()
  await page.getByRole('combobox', { name: 'Bazy wiedzy' }).click()
  await page.getByRole('option', { name: DATASET_NAME }).click()
  await page.getByRole('tab', { name: 'Silnik promptu' }).click()
  await page.getByLabel('Prompt systemowy').fill(SYSTEM_PROMPT)
  await page.getByRole('button', { name: 'Zapisz' }).click()
  await expect(page.getByRole('tab', { name: 'Asystent' })).toBeHidden()

  // 5. Odpowiedź asystenta: niepusta (fake-chat z blokiem wiedzy pisze „Na podstawie źródeł: …”,
  //    K10 §4) i z przypisem cytowania — `[ID:n]` front zamienia na chip „Cytowanie n” (DEC-243).
  await page.getByPlaceholder('Wpisz pytanie…').fill(question)
  await page.getByRole('button', { name: 'Wyślij' }).click()
  const answer = page.getByRole('article', { name: 'Odpowiedź asystenta' }).last()
  await expect(answer).toContainText('Na podstawie źródeł', { timeout: 60_000 })
  const chip = answer.getByRole('button', { name: /^Cytowanie \d+$/ }).first()
  await expect(chip, 'odnośnik cytowania w odpowiedzi').toBeVisible()

  // 6. Klik w przypis → modal (rola `dialog`) z pełnym fragmentem; cały fragment w viewporcie.
  await chip.click()
  const citeDialog = page.getByRole('dialog').filter({
    has: page.getByRole('heading', { name: targetName }),
  })
  await expect(citeDialog).toBeVisible()
  const fragment = citeDialog.getByText(question)
  await expect(fragment).toBeVisible()
  await expectInsideViewport(page, fragment, `fragment cytowania ${targetName} (1280×800)`)
  await page.keyboard.press('Escape')
  await expect(citeDialog).toBeHidden()
})
