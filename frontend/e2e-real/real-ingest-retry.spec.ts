// Scenariusze E5-H8e (SC-E5-H8e-01…04): odporność długiego parsowania na przejściowe błędy
// bramki LLM, wstrzykiwane przez fake-llm (`POST /v1/fake/upstream-error`, K10). Spec jest
// ZIELONY po scaleniu E5-H8e T3/T4 (retry embeddingów/wizji w backendzie): 4 testy, plus
// SC-E5-H8e-03G przy `E2E_REAL_GUS=1`. Bieg: `WD_CI_SPEC=real-ingest-retry.spec.ts
// tools/dev/clean-install.sh`; wariant z rocznikiem GUS dodatkowo `E2E_REAL_GUS=1
// WD_CI_TIMEOUT_S=5400`. Bieg skrócony na stosie testowym (README „Bieg skrócony”): fixture
// multi-batch-120.pdf (120 stron), upload przez strefę drop dialogu (prawdziwy `DataTransfer`,
// helper `dropFile`).
// SC-01/02 (retry embeddingu) używają domyślnego parsera — wystarczająco dużo żądań embeddingu,
// by wstrzyknięcie `every` faktycznie strzeliło; SC-03/04 (OCR z cache / retry wizji) parsują
// przez `fake-ocr` (rejestracja na instancji fake-vision). Cache wizji (DEC-293) jest WSPÓLNY
// dla całego stosu i kluczowany obrazem strony + modelem + promptem, więc SC-04 (retry wizji)
// jest zadeklarowany PRZED SC-03: pierwszy OCR fixture'a w biegu musi iść z wstrzyknięciem 503,
// zanim cache pozna strony tego pliku. SC-E5-H8e-03G (na końcu pliku) biega tylko przy
// `E2E_REAL_GUS=1`: rocznik GUS (745 stron) z korpusu `WD_REAL_CORPUS`, pomiar ponowienia po
// trwałym błędzie embeddingu — bez tej zmiennej test jest pomijany, a pozostałe cztery biegną
// zawsze. Selektory jak użytkownik: role/etykiety/tekst (bez data-testid), bez SQL.
import { mkdirSync, readFileSync, readdirSync, writeFileSync } from 'node:fs'
import { basename, join } from 'node:path'
import { fileURLToPath } from 'node:url'

import { expect, test } from '@playwright/test'
import type { APIRequestContext, APIResponse, Locator, Page } from '@playwright/test'

import { dropFile } from './helpers/dnd'
import { fakeStats, setOcrDelay, setUpstreamError } from './helpers/fake-llm'
import type { FakeStats } from './helpers/fake-llm'

const ADMIN_EMAIL = process.env.WD_CI_ADMIN_EMAIL ?? ''
const ADMIN_PASSWORD = process.env.WD_CI_ADMIN_PASSWORD ?? ''

const PDF_NAME = 'multi-batch-120.pdf'
const PAGES = 120
const PDF_PATH = fileURLToPath(new URL('../e2e/fixtures/multi-batch-120.pdf', import.meta.url))

// Pełny bieg fixture'a na stosie testowym (konwersja + OCR fake-ocr + embedding): ~15–60 s.
const PARSE_TIMEOUT_MS = 240_000
// SC-02: limit z kontraktu §C5 (DEC-293: 3 próby × pętla ~15–31 s + przerwy ≈ 110–175 s);
// obserwacja clean-install 2026-10-14: „Błąd” po ~158 s (3 próby: błąd ~30 s, ponowienie po ~25 s),
// więc okno oczekiwania na stan końcowy musi sięgać powyżej górnej granicy kontraktu (175 s).
const EMBED_FAIL_TIMEOUT_MS = 210_000

// SC-E5-H8e-03G (E2E_REAL_GUS=1): rocznik GUS z korpusu (WD_REAL_CORPUS, tylko odczyt) — 745
// stron. Pierwsze parsowanie: render + OCR (fake-ocr 500 ms) + 3 próby zadania przy trwałym
// 502; ponowienie: render + OCR z cache + embedding. Limity z zapasem wobec budżetu testu 60 min.
const GUS_NAME = 'gus_rocznik_statystyczny_rp_2024.pdf'
const GUS_PAGES = 745
const CORPUS = process.env.WD_REAL_CORPUS ?? ''
const OUT = process.env.WD_REAL_OUT ?? ''
const GUS_FIRST_PARSE_TIMEOUT_MS = 2_100_000
const GUS_REPARSE_TIMEOUT_MS = 900_000

const DONE = /Sukces/
const FAILED = /Błąd/

type Envelope<T> = { code: number; message: string; data: T }

/** Rozwija kopertę RAGFlow: HTTP 200 + `code 0`, inaczej wyjątek (wzór: real-stop-progress). */
async function ok<T>(pending: Promise<APIResponse>, label: string): Promise<T> {
  const response = await pending
  const body = (await response.json()) as Envelope<T>
  expect(response.status(), `${label}: HTTP ${response.status()} — ${body.message}`).toBe(200)
  expect(body.code, `${label}: ${body.message}`).toBe(0)
  return body.data
}

/** Token administratora z API logowania — do rejestracji parsera fake-ocr (SC-01…04). */
async function apiLogin(request: APIRequestContext): Promise<string> {
  return ok<{ access_token: string }>(
    request.post('/api/v1/auth/login', {
      data: { email: ADMIN_EMAIL, password: ADMIN_PASSWORD },
    }),
    'POST /api/v1/auth/login',
  ).then((data) => data.access_token)
}

/**
 * Rejestruje parser `fake-ocr` (image2text) na instancji zasianego `fake-vision` (wzór:
 * real-stop-progress). Gdy model już jest w rejestrze (bieg wielokrotny na tym samym stosie),
 * sam wpis wystarcza — bez powtórnego POST-a (ten kończy się kopertą Conflict code 102).
 */
async function registerFakeOcrModel(request: APIRequestContext, token: string): Promise<void> {
  const headers = { authorization: `Bearer ${token}` }
  const models = await ok<{ name: string; provider_name: string; instance_name: string }[]>(
    request.get('/api/v1/models', { headers }),
    'GET /api/v1/models',
  )
  // Już zarejestrowany (bieg wielokrotny na tym samym stosie albo seed) — nic nie rób; powtórny
  // POST kończy się kopertą Conflict (code 102, „already exists”).
  if (models.some((model) => model.name === 'fake-ocr')) return
  const vision = models.find((model) => model.name === 'fake-vision')
  expect(vision, 'fake-vision w rejestrze modeli').toBeDefined()
  const response = await request.post(
    `/api/v1/providers/${vision!.provider_name}/instances/${vision!.instance_name}/models`,
    { headers, data: { model_name: 'fake-ocr', model_type: 'image2text' } },
  )
  await ok<unknown>(Promise.resolve(response), 'POST /providers/{name}/instances/{instance}/models')
}

async function loginAsAdmin(page: Page): Promise<void> {
  await page.goto('/datasets')
  // Decydować o logowaniu może widoczność FORMULARZA, nie URL: guard SPA weryfikuje token
  // asynchronicznie, więc świeży kontekst potrafi chwilę mieć URL /datasets i dopiero potem
  // odbić na /login, a strona zalogowana wcześniej w teście (2. dataset w SC-01) zostaje na
  // /datasets mimo wejścia w ten adres.
  const email = page.getByLabel('E-mail')
  const createButton = page.getByRole('button', { name: 'Utwórz dataset' }).first()
  // Pierwszy render SPA pod obciążeniem hosta potrafi przekroczyć domyślne 5 s expectu.
  await expect(email.or(createButton)).toBeVisible({ timeout: 60_000 })
  if (await email.isVisible()) {
    await email.fill(ADMIN_EMAIL)
    // `exact` — inaczej `getByLabel('Hasło')` trafia też w przycisk „Pokaż hasło”.
    await page.getByLabel('Hasło', { exact: true }).fill(ADMIN_PASSWORD)
    await page.getByRole('button', { name: 'Zaloguj się' }).click()
    const nav = page.getByRole('navigation')
    await expect(nav.getByRole('link', { name: 'Bazy wiedzy' })).toBeVisible()
    await nav.getByRole('link', { name: 'Bazy wiedzy' }).click()
  }
  await expect(page).toHaveURL(/\/datasets$/)
}

/** Tworzy dataset (pole embeddingu wypełnia się samo) i otwiera zakładkę Pliki. */
async function createDataset(page: Page, name: string): Promise<void> {
  await page.getByRole('button', { name: 'Utwórz dataset' }).first().click()
  const dialog = page.getByRole('dialog')
  await expect(dialog).toBeVisible()
  await dialog.getByLabel('Nazwa').fill(name)
  await dialog.getByRole('button', { name: 'Utwórz' }).click()
  await expect(page.getByRole('heading', { name })).toBeVisible()
}

/**
 * Loguje administratora, tworzy dataset i — gdy `ocr` — przełącza parser PDF na `fake-ocr`
 * w zakładce Konfiguracja (ścieżka użytkownika, wzór SC-06 real-stop-progress).
 */
async function openDataset(
  page: Page,
  request: APIRequestContext,
  name: string,
  { ocr }: { ocr: boolean },
): Promise<void> {
  const token = await apiLogin(request)
  if (ocr) await registerFakeOcrModel(request, token)
  await loginAsAdmin(page)
  await createDataset(page, name)
  if (ocr) {
    await page.getByRole('tab', { name: 'Konfiguracja' }).click()
    await expect(page).toHaveURL(/\/dataset\/configuration\//)
    await page.getByLabel('Parser PDF').click()
    await page.getByRole('option', { name: 'fake-ocr' }).click()
    await page.getByRole('button', { name: 'Zapisz' }).click()
    await expect(page.getByText('Zapisano')).toBeVisible()
    await page.getByRole('tab', { name: 'Pliki' }).click()
    await expect(page).toHaveURL(/\/dataset\/files\//)
  }
}

/** Wgrywa fixture przez strefę drop dialogu (DataTransfer) z „Parsuj po przesłaniu”. */
async function uploadPdf(page: Page): Promise<void> {
  await page.getByRole('button', { name: 'Prześlij plik' }).click()
  const dialog = page.getByRole('dialog')
  await expect(dialog.getByRole('heading', { name: 'Prześlij pliki' })).toBeVisible()
  const dropzone = dialog.getByRole('button', { name: 'Przeciągnij pliki tutaj' })
  await dropFile(page, dropzone, readFileSync(PDF_PATH), PDF_NAME, 'application/pdf')
  await expect(dialog.getByText(PDF_NAME)).toBeVisible()
  await expect(dialog.getByRole('switch', { name: 'Parsuj po przesłaniu' })).toBeChecked()
  await dialog.getByRole('button', { name: 'Prześlij' }).click()
  await expect(dialog.getByText('Przesłano', { exact: true })).toBeVisible({ timeout: 180_000 })
  await dialog.getByRole('button', { name: 'Gotowe' }).click()
  await expect(dialog).toBeHidden()
}

function documentRow(page: Page, name: string): Locator {
  return page.getByRole('row').filter({ hasText: name })
}

/**
 * Pełny log zadania: klik w chip/tekst statusu otwiera dialog „Log parsowania” (jak
 * użytkownik otwiera log dokumentu; wzór: readParseLog real-stop-progress).
 */
async function readParseLog(page: Page, trigger: Locator, name: string): Promise<string> {
  await trigger.click()
  const dialog = page.getByRole('dialog')
  await expect(dialog.getByRole('heading', { name: `Log parsowania — ${name}` })).toBeVisible()
  const text = await dialog.locator('pre').innerText()
  await dialog.getByRole('button', { name: 'Zamknij' }).click()
  await expect(dialog).toBeHidden()
  return text
}

/** Wyzwalacz logu dla dokumentu w stanie końcowym: chip „Sukces” albo „Błąd”. */
function finalStateTrigger(row: Locator): Locator {
  return row.getByRole('button', { name: /^(Sukces|Błąd)$/ }).first()
}

/** Czaka aż wiersz pokaże stan końcowy („Sukces”/„Błąd”; wzór: waitForRowText). */
async function waitForFinalState(row: Locator, timeoutMs: number): Promise<void> {
  await expect
    .poll(
      async () => {
        const text = await row.innerText().catch(() => '')
        return DONE.test(text) || FAILED.test(text) ? 'hit' : 'pending'
      },
      { timeout: timeoutMs, intervals: [2_000] },
    )
    .not.toBe('pending')
}

/** Liczba chunków z wpisu „Generowanie N fragmentów” w logu zadania (widok użytkownika). */
function chunkCountFromLog(log: string, label: string): number {
  const match = /Generowanie (\d+) fragmentów/.exec(log)
  expect(match, `${label}: wpis „Generowanie N fragmentów” w logu`).not.toBeNull()
  return Number(match![1])
}

/** Suma żądań chat ze statystyki fake-llm (wszystkie modele) — miara żądań wizji (SC-03). */
function totalChatRequests(stats: FakeStats): number {
  return Object.values(stats.chat_completions).reduce((sum, count) => sum + count, 0)
}

// ——— SC-E5-H8e-03G: rocznik GUS (E2E_REAL_GUS=1) ———

/** Rekurencyjna lista plików katalogu (wzór: real-stop-progress). */
function walk(dir: string, acc: string[]): void {
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const full = join(dir, entry.name)
    if (entry.isDirectory()) walk(full, acc)
    else if (entry.isFile()) acc.push(full)
  }
}

/** Ścieżka rocznika w korpusie (WD_REAL_CORPUS; wzór: pdfPath real-stop-progress). */
function gusPdfPath(): string {
  if (CORPUS === '') throw new Error('WD_REAL_CORPUS nieustawione')
  const paths: string[] = []
  walk(CORPUS, paths)
  const hit = paths.find((path) => basename(path) === GUS_NAME)
  if (hit === undefined) throw new Error(`korpus: brak pliku ${GUS_NAME} pod ${CORPUS}`)
  return hit
}

/**
 * Wgrywa plik przez okno wyboru z domyślnym „Parsuj po przesłaniu” (wzór: real-stop-progress) —
 * dla dużego PDF-u rocznika zamiast `dropFile`, bez czytania pliku do pamięci procesu.
 */
async function uploadFile(page: Page, file: string): Promise<void> {
  await page.getByRole('button', { name: 'Prześlij plik' }).click()
  const dialog = page.getByRole('dialog')
  await expect(dialog.getByRole('heading', { name: 'Prześlij pliki' })).toBeVisible()
  await expect(dialog.getByRole('switch', { name: 'Parsuj po przesłaniu' })).toBeChecked()
  const chooser = page.waitForEvent('filechooser')
  await dialog.getByRole('button', { name: 'Wybierz pliki' }).click()
  await (await chooser).setFiles(file)
  await dialog.getByRole('button', { name: 'Prześlij' }).click()
  await expect(dialog.getByText('Przesłano', { exact: true })).toBeVisible({ timeout: 180_000 })
  await dialog.getByRole('button', { name: 'Gotowe' }).click()
}

const round1 = (value: number): number => Math.round(value * 10) / 10

/** Sekundy z prefiksu `HH:MM:SS` linii logu zadania (format linii: `clock_hms`, UTC). */
function lineClockSeconds(line: string): number {
  const match = /^(\d{2}):(\d{2}):(\d{2})/.exec(line)
  expect(match, `prefiks HH:MM:SS w linii logu: ${line.slice(0, 60)}`).not.toBeNull()
  return Number(match![1]) * 3600 + Number(match![2]) * 60 + Number(match![3])
}

/**
 * Czas etapu (s) z różnicy znaczników `HH:MM:SS` pierwszej linii pasującej do `startPattern` i do
 * `endPattern` (oba z tego samego zadania — `progress_msg` jest czyszczony na start; przejście
 * przez północ dolicza 24 h).
 */
function logStageSeconds(
  log: string,
  startPattern: RegExp,
  endPattern: RegExp,
  label: string,
): number {
  const start = log.split('\n').find((line) => startPattern.test(line))
  const end = log.split('\n').find((line) => endPattern.test(line))
  expect(start, `${label}: linia startu w logu`).toBeDefined()
  expect(end, `${label}: linia końca w logu`).toBeDefined()
  const from = lineClockSeconds(start!)
  const to = lineClockSeconds(end!)
  return to >= from ? to - from : to + 86_400 - from
}

test.afterEach(async () => {
  // Po każdym teście zdejmij wstrzykiwanie 5xx obu tras (brief T2: reset every:0 w afterEach);
  // błąd czyszczenia nie może zalać wyniku testu — kolejny test ustawia swoje wstrzykiwanie.
  await Promise.allSettled([
    setUpstreamError({ route: 'embeddings', every: 0, status: 502 }),
    setUpstreamError({ route: 'chat', every: 0, status: 503 }),
  ])
})

test('SC-E5-H8e-01 (real): pojedynczy 502 embeddingu — „Sukces”, ponowienie w logu, chunki jak bieg bez błędów', async ({
  page,
  request,
}) => {
  test.setTimeout(600_000)

  // Bieg referencyjny bez błędów — źródło oczekiwanej liczby chunków (ten sam fixture).
  // Domyślny parser (bez fake-ocr): fixture przy fake-ocr daje 2 chunki → zaledwie 2 żądania
  // embeddingu (tytuł + 1 partia), więc wstrzykiwanie `every:3` nie trafiłoby nigdy; domyślny
  // parser daje 173 chunki → tytuł + 3 partie = 4 żądania i 502 w żądaniu nr 3 („pojedynczy
  // 502” z tytułu scenariusza). SC-03/04 zostają na fake-ocr — tam OCR jest istotą scenariusza.
  await openDataset(page, request, 'Retry A — referencja', { ocr: false })
  await uploadPdf(page)
  const refRow = documentRow(page, PDF_NAME)
  await waitForFinalState(refRow, PARSE_TIMEOUT_MS)
  const refLog = await readParseLog(page, finalStateTrigger(refRow), PDF_NAME)
  const refChunks = chunkCountFromLog(refLog, 'bieg referencyjny')

  // Pojedynczy 502 embeddingu (co 3. żądanie, dwa wstrzyknięcia). Ustawiane PRZED uploadem —
  // wariant dopuszczony przez brief („PRZED uploadem/parsowaniem albo w trakcie”); przy tempie
  // stosu testowego ustawianie „w trakcie” ścigałoby się z końcem parsowania.
  await setUpstreamError({ route: 'embeddings', every: 3, status: 502, times: 2 })
  await openDataset(page, request, 'Retry B — pojedynczy 502', { ocr: false })
  await uploadPdf(page)
  const row = documentRow(page, PDF_NAME)
  await waitForFinalState(row, 2 * PARSE_TIMEOUT_MS)
  await expect(
    row,
    'SC-01: dokument kończy się „Sukces” mimo pojedynczego 502 (retry)',
  ).toContainText(DONE)

  const log = await readParseLog(page, finalStateTrigger(row), PDF_NAME)
  // Wpisy ponowień (rate_limit.py) i bilansu cache OCR są poza tabelą P1–P29 INVENTORY —
  // tłumaczenie logu (T3b) zostawia je dosłownie, asercja trzyma angielskie brzmienie (T9).
  expect(log, 'wpis ponowienia embeddingu w logu zadania').toContain(
    'Embedding provider error 502 — retry',
  )
  const chunks = chunkCountFromLog(log, 'bieg z 502')
  expect(chunks, 'liczba chunków równa biegowi bez błędów').toBe(refChunks)
})

test('SC-E5-H8e-02 (real): trwały 502 embeddingu — „Błąd” ≤ 210 s, komunikat bez stack trace', async ({
  page,
  request,
}) => {
  test.setTimeout(EMBED_FAIL_TIMEOUT_MS + 15_000)

  // Zawsze-502 (every:1, bez limitu) PRZED uploadem: pierwsze żądanie embeddingu pada, więc
  // czas biegu idzie w próby zadania i backoff, nie w parsowanie — limit 210 s z kontraktu.
  // Domyślny parser (bez OCR): scenariusz SC-02 nie dotyczy OCR.
  await setUpstreamError({ route: 'embeddings', every: 1, status: 502 })
  await openDataset(page, request, 'Retry C — trwały 502', { ocr: false })
  await uploadPdf(page)
  const row = documentRow(page, PDF_NAME)
  await waitForFinalState(row, EMBED_FAIL_TIMEOUT_MS - 25_000)
  await expect(row, 'SC-02: dokument kończy się „Błąd”').toContainText(FAILED)

  const log = await readParseLog(page, finalStateTrigger(row), PDF_NAME)
  expect(log, 'komunikat niedostępności embeddingu w podpowiedzi/logu statusu').toContain(
    'Embedding provider unavailable (502)',
  )
  expect(log, 'komunikat bez stack trace').not.toMatch(/Traceback|File "\//)
})

test('SC-E5-H8e-04 (real): 5xx wizji w trakcie OCR — „Sukces”, ponowienie w logu', async ({
  page,
  request,
}) => {
  test.setTimeout(600_000)

  // Cache wizji (DEC-293) jest współdzielony przez cały stos (klucz: obraz strony + model +
  // prompt), więc ten test MUSI wykonać pierwszy OCR fixture'a w biegu — deklaracja PRZED SC-03
  // (workers: 1 → kolejność deklaracji = kolejność wykonania). Po OCR w SC-03 wszystkie 120
  // stron siedziałoby w cache („OCR pages: 120 from cache, 0 to model”) i żaden wstrzyknięty
  // 503 nie dotarłby do modelu; SC-03 wykonywane potem ma ciepły cache, a jego asercje dotyczą
  // ponowienia („from cache”, wzrost żądań wizji = 0) i trzymają niezależnie od tego.
  // Wstrzyknięcie 503 czatu (wizji) co 5. żądanie, trzy razy — ustawione przed uploadem, więc
  // trafienia wypadają W TRAKCIE OCR (scenariusz: „w trakcie OCR”); zimny OCR fixture'a daje
  // 120 żądań wizji (OCR concurrency 3), więc every:5 × times:3 trafia 3 razy (żądania 5/10/15).
  await openDataset(page, request, 'Retry E — wizja 503', { ocr: true })
  const statsBefore = await fakeStats()
  await setUpstreamError({ route: 'chat', every: 5, status: 503, times: 3 })
  await uploadPdf(page)
  const row = documentRow(page, PDF_NAME)
  await waitForFinalState(row, 480_000)
  await expect(row, 'SC-04: dokument kończy się „Sukces” mimo 5xx wizji (retry)').toContainText(
    DONE,
  )

  // Dowód wstrzyknięcia: licznik wstrzykniętych 5xx trasy `chat` w fake-llm musiał wzrosnąć
  // (między pomiarami ten test jest jedynym źródłem żądań chat — bieg jest szeregowy).
  const statsAfter = await fakeStats()
  expect(
    statsAfter.upstream_errors.chat - statsBefore.upstream_errors.chat,
    'SC-04: wstrzyknięcie padło — licznik upstream_errors.chat wzrósł',
  ).toBeGreaterThanOrEqual(1)

  const log = await readParseLog(page, finalStateTrigger(row), PDF_NAME)
  expect(log, 'wpis ponowienia wizji w logu zadania').toContain('Vision provider error 503 — retry')
})

test('SC-E5-H8e-03 (real): ponowienie po trwałym błędzie nie powtarza OCR (cache, statystyka wizji)', async ({
  page,
  request,
}) => {
  test.setTimeout(600_000)

  // Stan wyjściowy jak SC-02: trwały 502 embeddingu → „Błąd” (parser fake-ocr — OCR ma co
  // cache'ować). Po SC-04 cache stron fixture'a jest już ciepły — asercje poniżej dotyczą
  // PONOWIENIA („from cache”, wzrost żądań wizji = 0) i trzymają na ciepłym cache tym bardziej.
  await setUpstreamError({ route: 'embeddings', every: 1, status: 502 })
  await openDataset(page, request, 'Retry D — OCR z cache', { ocr: true })
  await uploadPdf(page)
  const row = documentRow(page, PDF_NAME)
  await waitForFinalState(row, 300_000)
  await expect(row, 'SC-03: dokument po trwałym 502 jest w stanie „Błąd”').toContainText(FAILED)

  const visionBefore = totalChatRequests(await fakeStats())
  // Zdejmij błąd i ponów jak użytkownik: ↻ „Parsuj ponownie” w wierszu (0 chunków → bez dialogu).
  await setUpstreamError({ route: 'embeddings', every: 0, status: 502 })
  const reparseStartedAt = Date.now()
  await row.getByRole('button', { name: 'Parsuj ponownie' }).click()
  await waitForFinalState(row, 300_000)
  const reparseSeconds = Math.round((Date.now() - reparseStartedAt) / 1000)

  const log = await readParseLog(page, finalStateTrigger(row), PDF_NAME)
  // Bilans cache OCR (ingest_ocr_pipeline.py) poza tabelą P1–P29 → w dialogu dosłownie (EN).
  expect(log, `OCR ze cache w logu ponowienia (pomiar: ${reparseSeconds} s)`).toContain(
    `OCR pages: ${PAGES} from cache`,
  )
  const visionAfter = totalChatRequests(await fakeStats())
  expect(visionAfter - visionBefore, 'liczba żądań wizji nie rośnie przy ponowieniu').toBe(0)
  test
    .info()
    .annotations.push({ type: 'pomiar', description: `sc03-ponowienie-s=${reparseSeconds}` })
})

// SC-03G w osobnej grupie: skip na poziomie KOLEKCJONOWANIA (E2E_REAL_GUS) — bez zmiennej test
// jest pomijany, zanim Playwright postawi przeglądarkę (bieg bez rocznika nie wymaga jej).
test.describe('SC-E5-H8e-03G — bieg tylko przy E2E_REAL_GUS=1', () => {
  test.skip(
    process.env.E2E_REAL_GUS !== '1',
    'rocznik GUS (745 stron) biega tylko przy E2E_REAL_GUS=1 (brief T8)',
  )

  test('SC-E5-H8e-03G (real, GUS): ponowienie rocznika po trwałym błędzie nie powtarza OCR — odcinek OCR ≤ 30 s', async ({
    page,
    request,
  }) => {
    // Wyrocznia WP pkt 3: „SC-03 ponowienie ≤ render + embedding + 30 s” — pomiar na roczniku
    // (745 stron, fake-ocr 500 ms).
    test.setTimeout(3_600_000)

    // Opóźnienie fake-ocr 500 ms PRZED pierwszym parsowaniem (brief T8); przywraca je koniec tego
    // testu, a zdjęcie wstrzykiwania 5xx robi wspólne afterEach.
    await setOcrDelay(500)
    // Stan wyjściowy jak SC-03: trwały 502 embeddingu → „Błąd” (po renderze i OCR rocznika).
    await setUpstreamError({ route: 'embeddings', every: 1, status: 502 })
    await openDataset(page, request, 'Retry G — rocznik GUS', { ocr: true })
    await uploadFile(page, gusPdfPath())
    // t0 pierwszego parsowania: po zamknięciu dialogu uploadu (zadanie idzie do kolejki tuż po
    // „Przesłano”; pomiar informacyjny — budżet dotyczy wyłącznie odcinka OCR ponowienia).
    const firstStartedAt = Date.now()
    const row = documentRow(page, GUS_NAME)
    await waitForFinalState(row, GUS_FIRST_PARSE_TIMEOUT_MS)
    await expect(row, 'SC-03G: dokument po trwałym 502 jest w stanie „Błąd”').toContainText(FAILED)
    const firstParseToErrorS = round1((Date.now() - firstStartedAt) / 1000)

    // Ponowienie jak użytkownik: ↻ „Parsuj ponownie” z tą samą konfiguracją (0 chunków → bez
    // dialogu), błąd zdjęty przed kliknięciem.
    const chatBefore = totalChatRequests(await fakeStats())
    await setUpstreamError({ route: 'embeddings', every: 0, status: 502 })
    const reparseStartedAt = Date.now()
    await row.getByRole('button', { name: 'Parsuj ponownie' }).click()
    // expect.poll w waitForFinalState czyta wiersz OD RAZU (pierwsze wywołanie bez wstępnego
    // opóźnienia), a wiersz jeszcze chwilę pokazuje stary chip „Błąd” (POST → invalidate →
    // refetch): najpierw czekaj na zejście ze stanu końcowego, dopiero potem na stan końcowy
    // ponowienia (wyścig z review T8 — bez tego test gaśnie po ~5 s na asercji „Sukces”).
    await expect(row, 'wiersz opuszcza stan „Błąd” po kliknięciu ponowienia').not.toContainText(
      FAILED,
      { timeout: 60_000 },
    )
    await waitForFinalState(row, GUS_REPARSE_TIMEOUT_MS)
    await expect(row, 'SC-03G: ponowienie kończy się „Sukces”').toContainText(DONE)
    const reparseTotalS = round1((Date.now() - reparseStartedAt) / 1000)

    // Log PONOWIENIA: progress_msg jest czyszczony na start zadania, więc wpisy dotyczą tego biegu.
    const log = await readParseLog(page, finalStateTrigger(row), GUS_NAME)
    expect(
      log,
      `OCR ze cache w logu ponowienia (pierwsze parsowanie: ${firstParseToErrorS} s)`,
    ).toContain(`OCR pages: ${GUS_PAGES} from cache`)
    const chatAfter = totalChatRequests(await fakeStats())
    expect(chatAfter - chatBefore, 'liczba żądań wizji nie rośnie przy ponowieniu').toBe(0)

    // Etapy ponowienia z różnic znaczników HH:MM:SS w logu (wpisy przetłumaczone na PL od T3b):
    // render — od startu zadania („Zadanie przyjęte.”) do linii „Skonwertowano 745 stron”,
    // embedding — od „Generowanie N fragmentów” do „Indeksowanie zakończone”; OCR jako reszta
    // czasu całkowitego (wyrocznia: ponowienie ≤ render + embedding + 30 s).
    const reparseRenderS = round1(
      logStageSeconds(
        log,
        /Zadanie przyjęte\./,
        new RegExp(`Skonwertowano ${GUS_PAGES} stron`),
        'render',
      ),
    )
    const reparseEmbeddingS = round1(
      logStageSeconds(log, /Generowanie \d+ fragmentów/, /Indeksowanie zakończone/, 'embedding'),
    )
    const reparseOcrS = round1(reparseTotalS - reparseRenderS - reparseEmbeddingS)
    expect(
      reparseOcrS,
      `odcinek OCR ponowienia ≤ 30 s (total=${reparseTotalS}, render=${reparseRenderS}, embedding=${reparseEmbeddingS})`,
    ).toBeLessThanOrEqual(30)

    await setOcrDelay(0) // przywrócenie opóźnienia fake-ocr po teście (brief T8; every:0 — afterEach)

    // Pomiary do raportu TL: adnotacje + jedna linia JSON + plik (konwencja WD_REAL_OUT,
    // wzór: real-stop-progress).
    const measurements = {
      scenario: 'SC-E5-H8e-03G',
      pdf: GUS_NAME,
      pages: GUS_PAGES,
      first_parse_to_error_s: firstParseToErrorS,
      reparse_total_s: reparseTotalS,
      reparse_render_s: reparseRenderS,
      reparse_embedding_s: reparseEmbeddingS,
      reparse_ocr_s: reparseOcrS,
    }
    for (const [key, value] of Object.entries(measurements)) {
      if (key === 'scenario' || key === 'pdf') continue
      test.info().annotations.push({ type: 'pomiar', description: `${key}=${value}` })
    }
    console.log(`SC03G ${JSON.stringify(measurements)}`)
    if (OUT !== '') {
      mkdirSync(OUT, { recursive: true })
      writeFileSync(
        join(OUT, 'real-ingest-retry.json'),
        `${JSON.stringify(measurements, null, 2)}\n`,
      )
    }
  })
})
