// Scenariusze E5-H8b (brief T4): „Równoległe zapytania” modelu wizji (`extra.max_concurrency`,
// K13 poprawka 2026-10-10) steruje liczbą jednoczesnych zapytań OCR w workerze — bez restartu
// (SC-E5-H8b-01) — oraz pomiar etapów parsowania na fake (SC-E5-H8b-03): opóźnienie 0,58 s
// przy max_concurrency=24 daje ≈ 0,58/24 s efektywnie na stronę (pełny bieg: rocznik GUS na
// stosie clean-install; bieg skrócony E2E_REAL_QUICK=1 → multi-batch-120.pdf, stos testowy).
// Parser OCR = model `fake-ocr` — faktyczna nazwa modelu OCR na liście modeli fake-llm (K10 §2),
// jedyny, do którego stosuje się opóźnienie `/v1/fake/ocr-delay`; rejestrowany na instancji
// zasianego `fake-vision` (jak SC-06 w real-stop-progress). Zmianę „Równoległych zapytań”
// robi PATCH modelu (K13 §3 wiersz 9, pełne `extra` — obiekt zastępowany); UI pola to E5-H8c.
// Bez restartu workera: spec nigdy nie woła `restartContainer`, a identyfikator kontenera
// workera porównujemy przed i po zadaniach.
// Selektory jak użytkownik: role/etykiety/tekst (bez data-testid), bez SQL (konwencja e2e-real).
import { execFileSync } from 'node:child_process'
import { mkdirSync, readdirSync, writeFileSync } from 'node:fs'
import { basename, join } from 'node:path'
import { fileURLToPath } from 'node:url'

import { expect, test } from '@playwright/test'
import type { APIRequestContext, APIResponse, Locator, Page } from '@playwright/test'

import { fakeStats, maxConcurrent, ocrCount, resetFakeStats, setOcrDelay } from './helpers/fake-llm'
import { serviceContainerId } from './helpers/worker'

const ADMIN_EMAIL = process.env.WD_CI_ADMIN_EMAIL ?? ''
const ADMIN_PASSWORD = process.env.WD_CI_ADMIN_PASSWORD ?? ''
// Nazwa projektu compose (clean-install.sh; w biegu skróconym COMPOSE_PROJECT_NAME stosu
// testowego) i korpus wstrzykuje clean-install.sh (konwencja real-stop-progress).
const PROJECT = process.env.WD_CI_PROJECT ?? process.env.COMPOSE_PROJECT_NAME ?? ''
const CORPUS = process.env.WD_REAL_CORPUS ?? ''
const OUT = process.env.WD_REAL_OUT ?? ''

const FAKE_OCR = 'fake-ocr'
const QUICK = process.env.E2E_REAL_QUICK === '1'
const GUS_NAME = 'gus_rocznik_statystyczny_rp_2024.pdf'
// SC-01: zawsze fixture 120 stron (deterministyczny licznik stron dla budżetu stron×0,5/8);
// SC-03: bieg skrócony — fixture, pełny — rocznik z korpusu (745 stron).
const FIXTURE_NAME = 'multi-batch-120.pdf'
const FIXTURE_PAGES = 120
const THREE_PAGES_NAME = 'three-pages.pdf'
const PDF_NAME_03 = QUICK ? FIXTURE_NAME : GUS_NAME
const PAGES_03 = QUICK ? FIXTURE_PAGES : 745

// SC-E5-H8b-01: opóźnienie 500 ms/stronę, „Równoległe zapytania” 8 → faza OCR ≈ 120×0,5/8 s.
const DELAY_01_MS = 500
const MAX_01 = 8
// Narzut fazy OCR (górna granica luźna, brief T4 p. 1): raport co stronę, obrazy, kolejki.
const OCR_NARZUT_S = 30
// SC-E5-H8b-03: opóźnienie 580 ms i max_concurrency=24 (≈ 0,58/24 s na stronę, SCENARIOS SC-03).
const DELAY_03_MS = 580
const MAX_03 = 24
// Górny budżet SC-03 tylko dla rocznika: całość ≤ 12 min (SCENARIOS R-ING-06).
const TOTAL_BUDGET_FULL_S = 720

// Budżety oczekiwania: fixture do „Sukces” (wzór: 240 s w real-stop-progress + faza OCR);
// rocznik — PARSE_TIMEOUT wzorca + zapas; pierwszy postęp w wierszu.
const PARSE_TIMEOUT_01_MS = 360_000
const PARSE_TIMEOUT_03_MS = QUICK ? 360_000 : 1_500_000
const FIRST_PROGRESS_TIMEOUT_MS = 300_000

const DONE = /Sukces/
const FAILED = /Błąd/

const COLLECT_SH = fileURLToPath(new URL('../../tools/dev/real/collect.sh', import.meta.url))
const FIXTURE_120 = fileURLToPath(new URL('../e2e/fixtures/multi-batch-120.pdf', import.meta.url))
const THREE_PAGES = fileURLToPath(new URL('../e2e/fixtures/three-pages.pdf', import.meta.url))

/** Ścieżka rocznika GUS w korpusie (tylko odczyt; wzór: real-stop-progress.spec.ts). */
function gusPath(): string {
  if (CORPUS === '') throw new Error('WD_REAL_CORPUS nieustawione')
  const paths: string[] = []
  walk(CORPUS, paths)
  const hit = paths.find((path) => basename(path) === GUS_NAME)
  if (hit === undefined) throw new Error(`korpus: brak pliku ${GUS_NAME} pod ${CORPUS}`)
  return hit
}

/** Rekurencyjna lista plików katalogu (wzór: real-stop-progress.spec.ts). */
function walk(dir: string, acc: string[]): void {
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const full = join(dir, entry.name)
    if (entry.isDirectory()) walk(full, acc)
    else if (entry.isFile()) acc.push(full)
  }
}

type Envelope<T> = { code: number; message: string; data: T }

/** Rozwija kopertę RAGFlow: HTTP 200 + `code 0`, inaczej wyjątek (wzór: real-stop-progress). */
async function ok<T>(pending: Promise<APIResponse>, label: string): Promise<T> {
  const response = await pending
  const body = (await response.json()) as Envelope<T>
  expect(response.status(), `${label}: HTTP ${response.status()} — ${body.message}`).toBe(200)
  expect(body.code, `${label}: ${body.message}`).toBe(0)
  return body.data
}

/** Token administratora z API logowania — do PATCH modelu (UI pola dopiero E5-H8c). */
async function apiLogin(request: APIRequestContext): Promise<string> {
  const data = await ok<{ access_token: string }>(
    request.post('/api/v1/auth/login', {
      data: { email: ADMIN_EMAIL, password: ADMIN_PASSWORD },
    }),
    'POST /api/v1/auth/login',
  )
  return data.access_token
}

/**
 * Rejestruje model `fake-ocr` (image2text) na instancji zasianego `fake-vision` — raz; gdy
 * model już jest (drugi test w specie), tylko zwraca trasę instancji (POST dałby 102).
 */
async function registerFakeOcrModel(
  request: APIRequestContext,
  token: string,
): Promise<{ providerName: string; instanceName: string }> {
  const headers = { authorization: `Bearer ${token}` }
  const models = await ok<{ name: string; provider_name: string; instance_name: string }[]>(
    request.get('/api/v1/models', { headers }),
    'GET /api/v1/models',
  )
  const vision = models.find((model) => model.name === 'fake-vision')
  expect(vision, 'fake-vision w rejestrze modeli').toBeDefined()
  const providerName = vision!.provider_name
  const instanceName = vision!.instance_name
  if (!models.some((model) => model.name === FAKE_OCR)) {
    await ok<unknown>(
      request.post(`/api/v1/providers/${providerName}/instances/${instanceName}/models`, {
        headers,
        data: { model_name: FAKE_OCR, model_type: 'image2text' },
      }),
      'POST /providers/{name}/instances/{instance}/models',
    )
  }
  return { providerName, instanceName }
}

/** Aktualne `extra` modelu z listy modeli instancji (K13 §3 wiersz 7); `{}` gdy puste. */
async function currentExtra(
  request: APIRequestContext,
  token: string,
  providerName: string,
  instanceName: string,
): Promise<Record<string, unknown>> {
  const headers = { authorization: `Bearer ${token}` }
  const models = await ok<{ name: string; extra: Record<string, unknown> | null }[]>(
    request.get(`/api/v1/providers/${providerName}/instances/${instanceName}/models`, { headers }),
    'GET /providers/{name}/instances/{instance}/models',
  )
  const model = models.find((entry) => entry.name === FAKE_OCR)
  expect(model, `model ${FAKE_OCR} w rejestrze instancji`).toBeDefined()
  return model!.extra ?? {}
}

/** „Równoległe zapytania” modelu: PATCH pełnego `extra` z nowym `max_concurrency` (K13 §3 w. 9). */
async function patchMaxConcurrency(
  request: APIRequestContext,
  token: string,
  providerName: string,
  instanceName: string,
  maxConcurrency: number,
): Promise<void> {
  const headers = { authorization: `Bearer ${token}` }
  const extra = await currentExtra(request, token, providerName, instanceName)
  await ok<unknown>(
    request.patch(
      `/api/v1/providers/${providerName}/instances/${instanceName}/models/${FAKE_OCR}`,
      { headers, data: { extra: { ...extra, max_concurrency: maxConcurrency } } },
    ),
    `PATCH models/${FAKE_OCR} (max_concurrency=${maxConcurrency})`,
  )
}

async function loginAsAdmin(page: Page): Promise<void> {
  await page.goto('/login')
  await page.getByLabel('E-mail').fill(ADMIN_EMAIL)
  // `exact` — inaczej `getByLabel('Hasło')` trafia też w przycisk „Pokaż hasło”.
  await page.getByLabel('Hasło', { exact: true }).fill(ADMIN_PASSWORD)
  await page.getByRole('button', { name: 'Zaloguj się' }).click()
  const nav = page.getByRole('navigation')
  await expect(nav.getByRole('link', { name: 'Bazy wiedzy' })).toBeVisible()
  await nav.getByRole('link', { name: 'Bazy wiedzy' }).click()
  await expect(page).toHaveURL(/\/datasets$/)
}

/** Tworzy dataset domyślnym modelem instancji (pole embeddingu wypełnia się samo). */
async function createDataset(page: Page, name: string): Promise<void> {
  await page.getByRole('button', { name: 'Utwórz dataset' }).first().click()
  const dialog = page.getByRole('dialog')
  await expect(dialog).toBeVisible()
  await dialog.getByLabel('Nazwa').fill(name)
  await dialog.getByRole('button', { name: 'Utwórz' }).click()
  await expect(page.getByRole('heading', { name })).toBeVisible()
}

/** Parser PDF = model wizji w zakładce Konfiguracja (ścieżka użytkownika; wzór: SC-06). */
async function chooseParser(page: Page, model: string): Promise<void> {
  await page.getByRole('tab', { name: 'Konfiguracja' }).click()
  await expect(page).toHaveURL(/\/dataset\/configuration\//)
  await page.getByLabel('Parser PDF').click()
  await page.getByRole('option', { name: model }).click()
  await page.getByRole('button', { name: 'Zapisz' }).click()
  await expect(page.getByText('Zapisano')).toBeVisible()
  await page.getByRole('tab', { name: 'Pliki' }).click()
  await expect(page).toHaveURL(/\/dataset\/files\//)
}

/** Upload przez okno wyboru z domyślnym „Parsuj po przesłaniu”; zwraca t0 (klik „Prześlij”). */
async function uploadFile(page: Page, file: string): Promise<number> {
  await page.getByRole('button', { name: 'Prześlij plik' }).click()
  const uploadDialog = page.getByRole('dialog')
  await expect(uploadDialog.getByRole('heading', { name: 'Prześlij pliki' })).toBeVisible()
  await expect(uploadDialog.getByRole('switch', { name: 'Parsuj po przesłaniu' })).toBeChecked()
  const chooser = page.waitForEvent('filechooser')
  await uploadDialog.getByRole('button', { name: 'Wybierz pliki' }).click()
  await (await chooser).setFiles(file)
  const startedAt = Date.now()
  await uploadDialog.getByRole('button', { name: 'Prześlij' }).click()
  await expect(uploadDialog.getByText('Przesłano', { exact: true })).toBeVisible({
    timeout: 180_000,
  })
  await uploadDialog.getByRole('button', { name: 'Gotowe' }).click()
  return startedAt
}

function documentRow(page: Page, name: string): Locator {
  return page.getByRole('row').filter({ hasText: name })
}

/**
 * Pełny log zadania: klik w tekst/chip statusu (jak użytkownik: „otwiera log zadania”)
 * otwiera dialog „Log parsowania” z całym `progress_msg` (wzór: real-stop-progress).
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

/** Czaka aż wiersz pokaże zadany stan (tekst wiersza; wzór: waitForRowText real-stop-progress). */
async function waitForRowText(row: Locator, pattern: RegExp, timeoutMs: number): Promise<string> {
  let text = ''
  await expect
    .poll(
      async () => {
        try {
          text = await row.innerText()
        } catch {
          return 'pending'
        }
        return pattern.test(text) ? 'hit' : 'pending'
      },
      { timeout: timeoutMs, intervals: [2_000] },
    )
    .not.toBe('pending')
  return text
}

/** Czeka na „Sukces” i zwraca log zadania; „Błąd” → błąd testu z fragmentem logu. */
async function successLog(
  page: Page,
  row: Locator,
  name: string,
  timeoutMs: number,
): Promise<string> {
  const text = await waitForRowText(row, /Sukces|Błąd/, timeoutMs)
  if (FAILED.test(text)) {
    const failureLog = await readParseLog(page, row.getByRole('button', { name: 'Błąd' }), name)
    throw new Error(`parsowanie zakończyło się błędem — log: ${failureLog.slice(-400)}`)
  }
  return readParseLog(page, row.getByRole('button', { name: 'Sukces' }), name)
}

/** Godzina `HH:MM:SS` z początku linii logu jako sekundy dnia; linia bez znacznika → null. */
function lineSeconds(line: string): number | null {
  const match = /^(\d{2}):(\d{2}):(\d{2}) /.exec(line)
  return match === null ? null : Number(match[1]) * 3600 + Number(match[2]) * 60 + Number(match[3])
}

/**
 * Czas (s) między OSTATNIĄ linią pasującą do `startRe` a OSTATNIĄ pasującą do `endRe`
 * (znaczniki `HH:MM:SS` UTC z progress_msg; „ostatnia” — bo „Osadzanie fragmentów” jest serią;
 * wpisy worka w dialogu logu są po polsku od T3b — regexy wg locales/pl/serverMsg.json).
 * Brak którejś linii → null; zawinięcie przez północ korygujemy +24 h (bieg nie trwa doby).
 */
function stageSeconds(log: string, startRe: RegExp, endRe: RegExp): number | null {
  const findLast = (re: RegExp): number | null => {
    let hit: number | null = null
    for (const line of log.split('\n')) {
      if (re.test(line)) hit = lineSeconds(line)
    }
    return hit
  }
  const start = findLast(startRe)
  const end = findLast(endRe)
  if (start === null || end === null) return null
  return end >= start ? end - start : end + 86_400 - start
}

const round1 = (value: number): number => Math.round(value * 10) / 10

// Po porażce testu zostaw artefakty diagnostyczne stosu (wzór: real-stop-progress.spec.ts).
test.afterEach(() => {
  const testInfo = test.info()
  if (testInfo.status === testInfo.expectedStatus || PROJECT === '') return
  const dir = join(OUT === '' ? 'test-results-real/report' : OUT, 'artifacts-concurrency')
  try {
    execFileSync(COLLECT_SH, [PROJECT, dir], { stdio: 'pipe', timeout: 120_000 })
  } catch (error) {
    console.log(`[concurrency] collect.sh nie powiódł się: ${(error as Error).message}`)
  }
})

test('SC-E5-H8b-01 (real): Równoległe zapytania OCR = 8 bez restartu; 40 → 101; 2 dla kolejnego zadania', async ({
  page,
  request,
}) => {
  test.setTimeout(600_000)
  expect(PROJECT, 'nazwa projektu compose (WD_CI_PROJECT albo COMPOSE_PROJECT_NAME)').not.toBe('')

  // Użytkownik: logowanie, dataset, parser PDF = fake-ocr; „Równoległe zapytania” = 8 zapisuje
  // PATCH modelu (UI pola dopiero E5-H8c), bez restartu workera.
  const token = await apiLogin(request)
  const { providerName, instanceName } = await registerFakeOcrModel(request, token)
  await loginAsAdmin(page)
  await createDataset(page, 'Współbieżność OCR — 8')
  await chooseParser(page, FAKE_OCR)
  await patchMaxConcurrency(request, token, providerName, instanceName, MAX_01)
  await setOcrDelay(DELAY_01_MS)
  await resetFakeStats()

  const workerCidBefore = serviceContainerId(PROJECT, 'worker')
  expect(workerCidBefore, 'kontener worker stosu działa').not.toBeNull()
  await uploadFile(page, FIXTURE_120)
  const row = documentRow(page, FIXTURE_NAME)
  await expect(row.getByRole('progressbar', { name: 'Postęp parsowania' })).toBeVisible({
    timeout: FIRST_PROGRESS_TIMEOUT_MS,
  })
  const log = await successLog(page, row, FIXTURE_NAME, PARSE_TIMEOUT_01_MS)

  // (a) log zadania: worker deklaruje współbieżność modelu przed konwersją (kontrakt C2;
  // P3 po polsku — dialog logu tłumaczy wpisy worka od T3b).
  expect(log, 'log zadania zawiera „Współbieżność OCR: 8”').toContain('Współbieżność OCR: 8')

  // (b) licznik fake-llm: maks. jednoczesnych zapytań fake-ocr = 8 (≥ 7 — zapas na harmonogram).
  const seen = await maxConcurrent(FAKE_OCR)
  expect(
    seen,
    `maks. jednoczesnych zapytań fake-ocr ≥ ${MAX_01 - 1}: ${seen}`,
  ).toBeGreaterThanOrEqual(MAX_01 - 1)
  expect(seen, `maks. jednoczesnych zapytań fake-ocr ≤ ${MAX_01}: ${seen}`).toBeLessThanOrEqual(
    MAX_01,
  )

  // (c) czas fazy OCR (Skonwertowano → OCR zakończone) ≈ strony×0,5/8 ±30% (+ narzut — góra luźna).
  const expectedOcrS = (FIXTURE_PAGES * DELAY_01_MS) / 1000 / MAX_01
  const ocrS = stageSeconds(log, / Skonwertowano \d+ stron/, / OCR zakończone/)
  expect(ocrS, 'log ma granice fazy OCR (Skonwertowano → OCR zakończone)').not.toBeNull()
  expect(
    ocrS!,
    `faza OCR ≥ 0,7×${expectedOcrS} s (strony×0,5/8): ${ocrS} s`,
  ).toBeGreaterThanOrEqual(expectedOcrS * 0.7)
  expect(
    ocrS!,
    `faza OCR ≤ 1,3×${expectedOcrS} s + ${OCR_NARZUT_S} s narzutu: ${ocrS} s`,
  ).toBeLessThanOrEqual(expectedOcrS * 1.3 + OCR_NARZUT_S)

  // (d) „Równoległe zapytania” = 40 → odrzucenie: kod 101 i komunikat K13 dosłownie.
  const headers = { authorization: `Bearer ${token}` }
  const extra = await currentExtra(request, token, providerName, instanceName)
  const refused = await request.patch(
    `/api/v1/providers/${providerName}/instances/${instanceName}/models/${FAKE_OCR}`,
    { headers, data: { extra: { ...extra, max_concurrency: 40 } } },
  )
  expect(refused.status(), 'PATCH 40: HTTP 200 (koperta RAGFlow)').toBe(200)
  const refusedBody = (await refused.json()) as { code: number; message: string }
  expect(refusedBody.code, 'PATCH 40 → kod 101 (K13 poprawka 2026-10-10)').toBe(101)
  expect(refusedBody.message).toBe('extra.max_concurrency must be an integer between 1 and 32')

  // (e) „Równoległe zapytania” = 2: KOLEJNE zadanie (three-pages.pdf — 3 strony, minimum,
  // które odróżnia 2 od braku limitu) jedzie z limitem 2, bez restartu workera.
  await patchMaxConcurrency(request, token, providerName, instanceName, 2)
  await resetFakeStats()
  await uploadFile(page, THREE_PAGES)
  const row2 = documentRow(page, THREE_PAGES_NAME)
  await expect(row2.getByRole('progressbar', { name: 'Postęp parsowania' })).toBeVisible({
    timeout: FIRST_PROGRESS_TIMEOUT_MS,
  })
  const log2 = await successLog(page, row2, THREE_PAGES_NAME, PARSE_TIMEOUT_01_MS)
  expect(log2, 'log drugiego zadania zawiera „Współbieżność OCR: 2”').toContain(
    'Współbieżność OCR: 2',
  )
  const seen2 = await maxConcurrent(FAKE_OCR)
  expect(
    seen2,
    `maks. jednoczesnych zapytań fake-ocr w drugim zadaniu ≤ 2: ${seen2}`,
  ).toBeLessThanOrEqual(2)

  // Bez restartu: ten sam identyfikator kontenera workera (spec nigdy nie woła restartContainer).
  expect(
    serviceContainerId(PROJECT, 'worker'),
    'kontener worker bez restartu (ten sam identyfikator)',
  ).toBe(workerCidBefore)
})

test('SC-E5-H8b-03 (real): pomiar fake — etapy parsowania przy 0,58 s i Równoległych zapytaniach 24', async ({
  page,
  request,
}) => {
  test.setTimeout(PARSE_TIMEOUT_03_MS + 300_000)
  expect(PROJECT, 'nazwa projektu compose (WD_CI_PROJECT albo COMPOSE_PROJECT_NAME)').not.toBe('')

  const token = await apiLogin(request)
  const { providerName, instanceName } = await registerFakeOcrModel(request, token)
  await loginAsAdmin(page)
  await createDataset(page, QUICK ? 'Współbieżność — pomiar 120' : 'Współbieżność — pomiar rocznik')
  await chooseParser(page, FAKE_OCR)
  await patchMaxConcurrency(request, token, providerName, instanceName, MAX_03)
  await setOcrDelay(DELAY_03_MS)
  await resetFakeStats()

  const path = QUICK ? FIXTURE_120 : gusPath()
  const startedAt = await uploadFile(page, path)
  const row = documentRow(page, PDF_NAME_03)
  await expect(row.getByRole('progressbar', { name: 'Postęp parsowania' })).toBeVisible({
    timeout: FIRST_PROGRESS_TIMEOUT_MS,
  })

  // Pętla pomiarowa: licznik fake-ocr co ~1 s (pierwsze żądanie OCR), wiersz co ~1 s do stanu
  // końcowego. Etapy render/OCR/embedding liczymy potem ze znaczników HH:MM:SS w logu zadania.
  let firstOcrMs: number | null = null
  let statsBusy = false
  let finalText = ''
  const deadline = Date.now() + PARSE_TIMEOUT_03_MS
  while (Date.now() < deadline) {
    const current = await row.innerText().catch(() => '')
    if (DONE.test(current) || FAILED.test(current)) {
      finalText = current
      break
    }
    if (!statsBusy) {
      statsBusy = true
      fakeStats()
        .then((stats) => {
          if (ocrCount(stats, FAKE_OCR) > 0 && firstOcrMs === null) {
            firstOcrMs = Date.now() - startedAt
          }
        })
        .catch(() => {})
        .finally(() => {
          statsBusy = false
        })
    }
    await page.waitForTimeout(1_000)
  }
  await page.waitForTimeout(1_500) // domknięcie ostatniej próbki licznika w locie

  if (FAILED.test(finalText)) {
    const failureLog = await readParseLog(
      page,
      row.getByRole('button', { name: 'Błąd' }),
      PDF_NAME_03,
    )
    throw new Error(`parsowanie zakończyło się błędem — log: ${failureLog.slice(-400)}`)
  }
  expect(finalText, 'parsowanie dochodzi do „Sukces”').toMatch(DONE)

  const log = await readParseLog(page, row.getByRole('button', { name: 'Sukces' }), PDF_NAME_03)
  const seen = await maxConcurrent(FAKE_OCR)
  expect(
    seen,
    `maks. jednoczesnych zapytań fake-ocr ≤ Równoległych zapytań (${MAX_03}): ${seen}`,
  ).toBeLessThanOrEqual(MAX_03)

  // Górny budżet czasu tylko dla rocznika: całość ≤ 12 min (SC-E5-H8b-03; bieg skrócony bez
  // limitów — pomiar).
  const totalS = stageSeconds(log, /Zadanie przyjęte\./, / Indeksowanie zakończone/)
  if (!QUICK) {
    expect(
      totalS,
      'log ma granice całego zadania (przyjęte → indeksowanie zakończone)',
    ).not.toBeNull()
    expect(totalS!, `całość rocznika ≤ ${TOTAL_BUDGET_FULL_S} s: ${totalS} s`).toBeLessThanOrEqual(
      TOTAL_BUDGET_FULL_S,
    )
  }

  const measurements = {
    scenario: 'SC-E5-H8b-03',
    pdf: PDF_NAME_03,
    pages: PAGES_03,
    fake_ocr_delay_ms: DELAY_03_MS,
    max_concurrency: MAX_03,
    render_s: stageSeconds(log, /Zadanie przyjęte\./, / Skonwertowano \d+ stron/),
    first_ocr_request_s: firstOcrMs === null ? null : round1(firstOcrMs / 1000),
    ocr_s: stageSeconds(log, / Skonwertowano \d+ stron/, / OCR zakończone/),
    embedding_s: stageSeconds(log, / OCR zakończone/, / Osadzanie fragmentów \(\d+\/\d+\)/),
    total_s: totalS,
    max_concurrent_seen: seen,
  }
  for (const [key, value] of Object.entries(measurements)) {
    if (key === 'scenario' || key === 'pdf') continue
    test.info().annotations.push({ type: 'pomiar', description: `${key}=${value}` })
  }
  console.log(`[concurrency] pomiar ${JSON.stringify(measurements)}`)
  if (OUT !== '') {
    mkdirSync(OUT, { recursive: true })
    writeFileSync(join(OUT, 'real-concurrency.json'), `${JSON.stringify(measurements, null, 2)}\n`)
  }
})
