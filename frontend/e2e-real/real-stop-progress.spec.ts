// Scenariusze E5-H8a w wariancie „prod” (brief T8): rocznik GUS na stosie produkcyjnym
// z nakładką fake-llm, stawianym przez tools/dev/clean-install.sh. SC-E5-H8a-04: postęp
// konwersji rośnie co ≤ 30 s, log ma ≥ 5 wpisów „Konwertowanie stron d/745”; SC-E5-H8a-01:
// Stop w trakcie konwersji → „Anulowano” ≤ 60 s, a log kończy się wpisem o anulowaniu
// („Zadanie anulowane.”); SC-E5-H8a-03: Stop i natychmiastowy restart kontenera workera
// — zadanie nie jest wznawiane, następny mały plik → „Sukces”; SC-E5-H8a-06: parser
// OCR = fake-ocr z opóźnieniem 500 ms — pierwsze żądanie OCR ≤ 30 s od startu zadania
// (potokowość), czas renderu do wpisu „Skonwertowano …” i szczyt RSS workera ≤ limitu
// kontenera. Bieg skrócony (E2E_REAL_QUICK=1) zastępuje rocznik fixture'em
// multi-batch-120.pdf — do samo-sprawdzenia specu bez 745-stronicowego parsowania.
// Selektory jak użytkownik: role/etykiety/tekst (bez data-testid), bez SQL (konwencja
// e2e-real). Od T3b dialog „Log parsowania” tłumaczy wpisy worka (serverMessages.ts,
// brzmienia PL: locales/pl/serverMsg.json) — asercje logu po polsku (T9).
import { execFileSync } from 'node:child_process'
import { mkdirSync, readdirSync, statSync, writeFileSync } from 'node:fs'
import { basename, join } from 'node:path'
import { fileURLToPath } from 'node:url'

import { expect, test } from '@playwright/test'
import type { APIRequestContext, APIResponse, Locator, Page } from '@playwright/test'

import { EXPECTED } from './corpus-expectations'
import { fakeStats, ocrCount, resetFakeStats, setOcrDelay } from './helpers/fake-llm'
import {
  containerMemoryLimitBytes,
  containerStats,
  restartContainer,
  serviceContainerId,
} from './helpers/worker'

const ADMIN_EMAIL = process.env.WD_CI_ADMIN_EMAIL ?? ''
const ADMIN_PASSWORD = process.env.WD_CI_ADMIN_PASSWORD ?? ''
// Nazwa projektu compose (clean-install.sh; w biegu skróconym COMPOSE_PROJECT_NAME stosu
// testowego) i korpus wstrzykuje clean-install.sh (konwencja real-resilience).
const PROJECT = process.env.WD_CI_PROJECT ?? process.env.COMPOSE_PROJECT_NAME ?? ''
const CORPUS = process.env.WD_REAL_CORPUS ?? ''
const OUT = process.env.WD_REAL_OUT ?? ''

const GUS_NAME = 'gus_rocznik_statystyczny_rp_2024.pdf'
const QUICK = process.env.E2E_REAL_QUICK === '1'
const PDF_NAME = QUICK ? 'multi-batch-120.pdf' : GUS_NAME
const PAGES = QUICK ? 120 : 745

// Budżety ze SCENARIOS.md: postęp co ≤ 30 s, Stop → „Anulowano” ≤ 60 s (rocznik), pierwsze
// żądanie OCR ≤ 30 s od startu zadania (potokowość, usterka Q34-10).
const SAMPLE_MS = 5_000
const PERCENT_GAP_MS = 30_000
const STOP_BUDGET_MS = 60_000
const FIRST_OCR_BUDGET_MS = 30_000
// Pierwsza partia (25 stron) na roczniku: render + raport — zapas na obciążenie hosta.
const FIRST_BATCH_TIMEOUT_MS = QUICK ? 120_000 : 300_000
// Pełne parsowanie rocznika do „Sukces” (pomiar renderu w raporcie TL); fixture — ~1 min.
const PARSE_TIMEOUT_MS = QUICK ? 240_000 : 1_200_000
// „Anulowano” po restarcie workera: start kontenera + release_own_host przy starcie (C5).
const RESTART_CANCEL_TIMEOUT_MS = QUICK ? 120_000 : 300_000
// Okno próbkowania SC-06: do pierwszego wpisu „OCR stron” (tani koniec — bez 745 stron OCR).
const OCR_SAMPLING_TIMEOUT_MS = QUICK ? 180_000 : 600_000

const DONE = /Sukces/
const FAILED = /Błąd/
const CANCELLED = /Anulowano/

const COLLECT_SH = fileURLToPath(new URL('../../tools/dev/real/collect.sh', import.meta.url))
const SAMPLE_PDF = fileURLToPath(new URL('../e2e/fixtures/sample.pdf', import.meta.url))
const QUICK_PDF = fileURLToPath(new URL('../e2e/fixtures/multi-batch-120.pdf', import.meta.url))

/** Ścieżka pliku PDF do parsowania: rocznik z korpusu (tylko odczyt) albo fixture skrótu. */
function pdfPath(): string {
  if (QUICK) return QUICK_PDF
  if (CORPUS === '') throw new Error('WD_REAL_CORPUS nieustawione')
  const paths: string[] = []
  walk(CORPUS, paths)
  const hit = paths.find((path) => basename(path) === GUS_NAME)
  if (hit === undefined) throw new Error(`korpus: brak pliku ${GUS_NAME} pod ${CORPUS}`)
  return hit
}

/** Rekurencyjna lista plików katalogu (wzór: real-resilience.spec.ts). */
function walk(dir: string, acc: string[]): void {
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const full = join(dir, entry.name)
    if (entry.isDirectory()) walk(full, acc)
    else if (entry.isFile()) acc.push(full)
  }
}

/**
 * Najmniejszy plik korpusu parsujący się do „Sukces” (SC-03: następny mały plik po restarcie).
 * Rocznik wykluczamy — to on właśnie stoi w „Anulowano”.
 */
function smallestSuccessFile(): string {
  if (CORPUS === '') throw new Error('WD_REAL_CORPUS nieustawione')
  const paths: string[] = []
  walk(CORPUS, paths)
  const candidates = paths.filter((path) => {
    const name = basename(path)
    const ext = name.split('.').pop()?.toLowerCase() ?? ''
    return name !== GUS_NAME && EXPECTED[ext] === 'success'
  })
  expect(candidates.length, 'korpus ma plik do parsowania po restarcie workera').toBeGreaterThan(0)
  return candidates.reduce((smallest, path) =>
    statSync(path).size < statSync(smallest).size ? path : smallest,
  )
}

type Envelope<T> = { code: number; message: string; data: T }

/** Rozwija kopertę RAGFlow: HTTP 200 + `code 0`, inaczej wyjątek (wzór: e2e/helpers/ocr.ts). */
async function ok<T>(pending: Promise<APIResponse>, label: string): Promise<T> {
  const response = await pending
  const body = (await response.json()) as Envelope<T>
  expect(response.status(), `${label}: HTTP ${response.status()} — ${body.message}`).toBe(200)
  expect(body.code, `${label}: ${body.message}`).toBe(0)
  return body.data
}

/** Token administratora z API logowania — do rejestracji modelu parsera (SC-06). */
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
 * Rejestruje model `fake-ocr` (image2text) na instancji, na której siedzi zasiany `fake-vision`
 * (na stosie clean-install rejestr zasiewa migracja z WD_LLM_DEFAULT_VLM; wzór: ocr.ts).
 * Bez wpisu zakładka Konfiguracja odrzuciłaby parser `fake-ocr` jako nieznany model.
 */
async function registerFakeOcrModel(request: APIRequestContext, token: string): Promise<void> {
  const headers = { authorization: `Bearer ${token}` }
  const models = await ok<{ name: string; provider_name: string; instance_name: string }[]>(
    request.get('/api/v1/models', { headers }),
    'GET /api/v1/models',
  )
  const vision = models.find((model) => model.name === 'fake-vision')
  expect(vision, 'fake-vision w rejestrze modeli').toBeDefined()
  await ok<unknown>(
    request.post(
      `/api/v1/providers/${vision!.provider_name}/instances/${vision!.instance_name}/models`,
      { headers, data: { model_name: 'fake-ocr', model_type: 'image2text' } },
    ),
    'POST /providers/{name}/instances/{instance}/models',
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

/** Upload przez okno wyboru z domyślnym „Parsuj po przesłaniu” (wzorzec real-resilience). */
async function uploadFile(page: Page, file: string): Promise<void> {
  await page.getByRole('button', { name: 'Prześlij plik' }).click()
  const uploadDialog = page.getByRole('dialog')
  await expect(uploadDialog.getByRole('heading', { name: 'Prześlij pliki' })).toBeVisible()
  await expect(uploadDialog.getByRole('switch', { name: 'Parsuj po przesłaniu' })).toBeChecked()
  const chooser = page.waitForEvent('filechooser')
  await uploadDialog.getByRole('button', { name: 'Wybierz pliki' }).click()
  await (await chooser).setFiles(file)
  await uploadDialog.getByRole('button', { name: 'Prześlij' }).click()
  await expect(uploadDialog.getByText('Przesłano', { exact: true })).toBeVisible({
    timeout: 180_000,
  })
  await uploadDialog.getByRole('button', { name: 'Gotowe' }).click()
}

function documentRow(page: Page, name: string): Locator {
  return page.getByRole('row').filter({ hasText: name })
}

/**
 * Pełny log zadania: klik w tekst/chip statusu (jak użytkownik: „otwiera log zadania”)
 * otwiera dialog „Log parsowania” z całym `progress_msg`.
 */
async function readParseLog(page: Page, trigger: Locator, name: string): Promise<string> {
  await trigger.click()
  const dialog = page.getByRole('dialog')
  await expect(dialog.getByRole('heading', { name: `Log parsowania — ${name}` })).toBeVisible()
  try {
    // Pusty `progress_msg` → „Brak logu” bez `<pre>`: zwracamy '' bez czekania na innerText.
    const pre = dialog.locator('pre')
    return (await pre.count()) > 0 ? await pre.innerText() : ''
  } finally {
    // Zawsze zamykamy modal, by pętla pomiarowa nie blokowała kolejnych kliknięć.
    await dialog.getByRole('button', { name: 'Zamknij' }).click()
    await expect(dialog).toBeHidden()
  }
}

/** Wyzwalacz dialogu logu dla dokumentu w biegu („N%” albo „W kolejce”). */
function runningLogTrigger(row: Locator): Locator {
  return row.getByRole('button', { name: /(\d+\s*%|W kolejce)/ }).first()
}

/** Czaka aż wiersz pokaże zadany stan (tekst wiersza; wzór: waitForFinalState real-resilience). */
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

const round1 = (value: number): number => Math.round(value * 10) / 10

test.describe.configure({ mode: 'serial' })

// Po porażce testu zostaw artefakty diagnostyczne stosu (wzór: real-resilience.spec.ts).
test.afterEach(() => {
  const testInfo = test.info()
  if (testInfo.status === testInfo.expectedStatus || PROJECT === '') return
  const dir = join(OUT === '' ? 'test-results-real/report' : OUT, 'artifacts-stop-progress')
  try {
    execFileSync(COLLECT_SH, [PROJECT, dir], { stdio: 'pipe', timeout: 120_000 })
  } catch (error) {
    console.log(`[stop-progress] collect.sh nie powiódł się: ${(error as Error).message}`)
  }
})

test('SC-E5-H8a-04 (real): postęp rocznika rośnie co ≤ 30 s, log ma ≥ 5 wpisów „Konwertowanie stron”', async ({
  page,
}) => {
  test.setTimeout(PARSE_TIMEOUT_MS + 300_000)

  await loginAsAdmin(page)
  await createDataset(page, 'Stop progress A — postęp')
  await uploadFile(page, pdfPath())
  const row = documentRow(page, PDF_NAME)
  await expect(row.getByRole('progressbar', { name: 'Postęp parsowania' })).toBeVisible({
    timeout: 300_000,
  })

  // Próbkowanie procentu wiersza co 5 s aż do stanu końcowego; notujemy momenty ZMIAN wartości.
  const startedAt = Date.now()
  const changes: { percent: number; at: number }[] = []
  let failureLog = ''
  let succeeded = false
  const deadline = Date.now() + PARSE_TIMEOUT_MS
  while (Date.now() < deadline) {
    let text = ''
    try {
      text = await row.innerText()
    } catch {
      // wiersz chwilowo niedostępny (odświeżenie siatki) — próbka jak brak tekstu
    }
    if (DONE.test(text)) {
      succeeded = true
      break
    }
    if (FAILED.test(text)) {
      failureLog = await readParseLog(page, row.getByRole('button', { name: 'Błąd' }), PDF_NAME)
      break
    }
    const percent = /(\d+)\s*%/.exec(text)
    if (percent !== null) {
      const value = Number(percent[1])
      const last = changes[changes.length - 1]
      if (last === undefined || last.percent !== value) {
        changes.push({ percent: value, at: Date.now() })
      }
    }
    await page.waitForTimeout(SAMPLE_MS)
  }
  expect(
    succeeded,
    `parsowanie rocznika dochodzi do „Sukces”${failureLog ? ` — log: ${failureLog.slice(0, 400)}` : ''}`,
  ).toBe(true)

  // Maksymalna przerwa między kolejnymi zmianami procentu ≤ 30 s (budżet SC-04).
  const gaps = changes.slice(1).map((change, index) => change.at - changes[index]!.at)
  const maxGap = Math.max(0, ...gaps)
  expect(
    maxGap,
    `największa przerwa między zmianami procentu ≤ 30 s (zmian: ${changes.length}, próbki co ${SAMPLE_MS / 1000} s)`,
  ).toBeLessThanOrEqual(PERCENT_GAP_MS)

  // Log zadania: licznik stron co partię (≥ 5 wpisów) i wpis końca konwersji (brzmienia PL
  // z locales/pl/serverMsg.json — P4 „Konwertowanie stron”, P6 „Skonwertowano N stron”).
  const log = await readParseLog(page, row.getByRole('button', { name: 'Sukces' }), PDF_NAME)
  const converting = log.match(new RegExp(`Konwertowanie stron \\d+/${PAGES}`, 'g')) ?? []
  expect(
    converting.length,
    `wpisów „Konwertowanie stron d/${PAGES}” w logu`,
  ).toBeGreaterThanOrEqual(5)
  expect(log, 'wpis końca konwersji').toContain(`Skonwertowano ${PAGES} stron`)

  const renderSeconds = round1((Date.now() - startedAt) / 1000)
  test
    .info()
    .annotations.push({ type: 'pomiar', description: `sc04-render-do-sukcesu-s=${renderSeconds}` })
  console.log(
    `[stop-progress] pomiar sc04: zmiany-procentu=${changes.length} maks-przerwa-s=${round1(maxGap / 1000)} render-do-sukcesu-s=${renderSeconds}`,
  )
})

test('SC-E5-H8a-01 (real): Stop w trakcie konwersji — „Anulowano” ≤ 60 s, log kończy anulowanie', async ({
  page,
}) => {
  test.setTimeout(QUICK ? 300_000 : 600_000)

  await loginAsAdmin(page)
  await createDataset(page, 'Stop progress B — Stop')
  await uploadFile(page, pdfPath())
  const row = documentRow(page, PDF_NAME)
  await expect(row.getByRole('progressbar', { name: 'Postęp parsowania' })).toBeVisible({
    timeout: 300_000,
  })

  // Stop w TRAKCIE konwersji: procent w wierszu pochodzi z tego samego raportu co wpis
  // „Konwertowanie stron d/N” (pierwsza skonwertowana partia), a 1% to tylko „Zadanie
  // przyjęte.” — dlatego czekamy na ≥ 2%. Klik od razu po progu: na szybkim stosie testowym
  // (fixture ~10 s) późniejszy klik mógłby trafić w nieświeży wiersz już po „Sukces”.
  const percentTrigger = row.getByRole('button', { name: /\d+\s*%/ })
  await expect(percentTrigger, 'wiersz pokazuje procent konwersji').toBeVisible({
    timeout: FIRST_BATCH_TIMEOUT_MS,
  })
  await expect
    .poll(
      async () => {
        const text = (await percentTrigger.textContent().catch(() => null)) ?? ''
        const match = /(\d+)\s*%/.exec(text)
        return match === null ? 0 : Number(match[1])
      },
      { timeout: FIRST_BATCH_TIMEOUT_MS, intervals: [1_000] },
    )
    .toBeGreaterThanOrEqual(2)
  const stopButton = row.getByRole('button', { name: 'Zatrzymaj parsowanie' })
  await expect(stopButton, 'przycisk Stop w wierszu').toBeVisible()
  await stopButton.click()
  await waitForRowText(row, CANCELLED, STOP_BUDGET_MS)

  // Odchyłka kontraktu C1: ostatni wpis logu to „HH:MM:SS Zadanie anulowane.” (P17) — dokładnie
  // jeden, a po nim brak wpisów konwersji/OCR/embeddingu (ostatnia pozycja w logu). Wpis
  // „Konwertowanie stron” w logu potwierdza, że Stop był w fazie konwersji (brief T8 p. 2).
  const finalLog = await readParseLog(
    page,
    row.getByRole('button', { name: 'Anulowano' }),
    PDF_NAME,
  )
  const lines = finalLog.split('\n').filter((line) => line.trim() !== '')
  expect(lines.length, 'log zadania niepusty').toBeGreaterThan(0)
  expect(finalLog, 'log ma wpis konwersji — Stop był w trakcie konwersji').toMatch(
    new RegExp(`Konwertowanie stron \\d+/${PAGES}`),
  )
  const cancelLines = lines.filter((line) => line.includes('Zadanie anulowane.'))
  expect(cancelLines, 'dokładnie jeden wpis o anulowaniu').toHaveLength(1)
  expect(lines[lines.length - 1], 'anulowanie jako ostatni wpis logu').toBe(cancelLines[0])
})

test('SC-E5-H8a-03 (real): Stop + natychmiastowy restart workera — zadanie nie jest wznawiane', async ({
  page,
}) => {
  test.setTimeout(QUICK ? 420_000 : 1_200_000)
  expect(PROJECT, 'nazwa projektu compose (WD_CI_PROJECT albo COMPOSE_PROJECT_NAME)').not.toBe('')
  const workerCid = serviceContainerId(PROJECT, 'worker')
  expect(workerCid, 'kontener worker stosu działa').not.toBeNull()

  await loginAsAdmin(page)
  await createDataset(page, 'Stop progress C — restart')
  await uploadFile(page, pdfPath())
  const row = documentRow(page, PDF_NAME)
  await expect(row.getByRole('progressbar', { name: 'Postęp parsowania' })).toBeVisible({
    timeout: 300_000,
  })
  // Zadanie biegnie na workerze (procent ≥ 2% = pierwsza partia skonwertowana, jak w SC-01) —
  // dopiero teraz Stop; na szybkim stosie testowym późniejszy klik mógłby trafić po „Sukces”.
  const percentTrigger = row.getByRole('button', { name: /\d+\s*%/ })
  await expect(percentTrigger, 'wiersz pokazuje procent konwersji').toBeVisible({
    timeout: FIRST_BATCH_TIMEOUT_MS,
  })
  await expect
    .poll(
      async () => {
        const text = (await percentTrigger.textContent().catch(() => null)) ?? ''
        const match = /(\d+)\s*%/.exec(text)
        return match === null ? 0 : Number(match[1])
      },
      { timeout: FIRST_BATCH_TIMEOUT_MS, intervals: [1_000] },
    )
    .toBeGreaterThanOrEqual(2)
  const stopButton = row.getByRole('button', { name: 'Zatrzymaj parsowanie' })
  await expect(stopButton, 'przycisk Stop w wierszu').toBeVisible()

  // Stop i natychmiast (≤ 1 s od kliknięcia — klik już wrócił) restart kontenera workera
  // (`docker restart --time 1`, sposób jak w real-resilience/kill.sh: po identyfikatorze
  // kontenera; 1 s łaski, żeby ściąć workera ZANIM dokończy zadanie).
  await stopButton.click()
  await restartContainer(workerCid!)

  // Po starcie workera zadanie NIE wraca do kolejki ani nie jest wznawiane (C5): dokument
  // przechodzi do „Anulowano” (release_own_host przy starcie).
  await waitForRowText(row, CANCELLED, RESTART_CANCEL_TIMEOUT_MS)

  // „Anulowano” zostaje po dojściu workera — 4 odczyty co 5 s łapią wznowienie, gdyby nastąpiło.
  for (let sample = 0; sample < 4; sample += 1) {
    await page.waitForTimeout(5_000)
    await expect(row, 'status pozostaje „Anulowano” po starcie workera').toContainText(CANCELLED)
  }

  // Następny mały plik (z korpusu; w skrócie sample.pdf) parsuje się do „Sukces”.
  const smallPath = QUICK ? SAMPLE_PDF : smallestSuccessFile()
  await uploadFile(page, smallPath)
  await expect(documentRow(page, basename(smallPath))).toContainText(DONE, { timeout: 240_000 })
})

test('SC-E5-H8a-06 (real): fake-ocr 500 ms — pierwsze żądanie ≤ 30 s, render, szczyt RSS', async ({
  page,
  request,
}) => {
  test.setTimeout(QUICK ? 420_000 : 1_200_000)
  const FAKE_OCR = 'fake-ocr'
  expect(PROJECT, 'nazwa projektu compose (WD_CI_PROJECT albo COMPOSE_PROJECT_NAME)').not.toBe('')

  // Parser OCR = fake-ocr: rejestracja modelu (na instancji fake-vision) i wybór w zakładce
  // Konfiguracja — ścieżka użytkownika (s06b: select + opcja + „Zapisz”).
  const token = await apiLogin(request)
  await registerFakeOcrModel(request, token)
  await loginAsAdmin(page)
  await createDataset(page, 'Stop progress D — fake-ocr')
  await page.getByRole('tab', { name: 'Konfiguracja' }).click()
  await expect(page).toHaveURL(/\/dataset\/configuration\//)
  await page.getByLabel('Parser PDF').click()
  await page.getByRole('option', { name: FAKE_OCR }).click()
  await page.getByRole('button', { name: 'Zapisz' }).click()
  await expect(page.getByText('Zapisano')).toBeVisible()
  await page.getByRole('tab', { name: 'Pliki' }).click()
  await expect(page).toHaveURL(/\/dataset\/files\//)

  // Opóźnienie fake-ocr 500 ms na żądanie i zerowanie liczników (C6; endpoint istnieje w K10).
  await setOcrDelay(500)
  await resetFakeStats()

  const workerCid = serviceContainerId(PROJECT, 'worker')
  expect(workerCid, 'kontener worker stosu działa').not.toBeNull()
  // Limit pamięci kontenera (WD_WORKER_MEM_LIMIT z compose); bez limitu — 4 GiB z docker-compose.yml.
  const limitBytes = (await containerMemoryLimitBytes(workerCid!)) ?? 4 * 1024 ** 3

  // Upload z pomiarem startu zadania: t0 = moment kliknięcia „Prześlij” (żądanie parsowania
  // idzie tuż po uploadzie pliku).
  await page.getByRole('button', { name: 'Prześlij plik' }).click()
  const uploadDialog = page.getByRole('dialog')
  await expect(uploadDialog.getByRole('heading', { name: 'Prześlij pliki' })).toBeVisible()
  await expect(uploadDialog.getByRole('switch', { name: 'Parsuj po przesłaniu' })).toBeChecked()
  const chooser = page.waitForEvent('filechooser')
  await uploadDialog.getByRole('button', { name: 'Wybierz pliki' }).click()
  await (await chooser).setFiles(pdfPath())
  const taskStartedAt = Date.now()
  await uploadDialog.getByRole('button', { name: 'Prześlij' }).click()
  await expect(uploadDialog.getByText('Przesłano', { exact: true })).toBeVisible({
    timeout: 180_000,
  })
  await uploadDialog.getByRole('button', { name: 'Gotowe' }).click()

  const row = documentRow(page, PDF_NAME)
  await expect(row.getByRole('progressbar', { name: 'Postęp parsowania' })).toBeVisible({
    timeout: 300_000,
  })

  // Pętla pomiarowa: licznik fake-ocr co ~1 s, RSS/CPU workera co ~2 s, log co ~2 s — do
  // pierwszego wpisu „OCR stron” (tani koniec: nie czekamy na 745 stron OCR, brief T8 p. 4).
  let firstOcrMs: number | null = null
  let renderMs: number | null = null
  let peakMemBytes = 0
  let peakCpuPercent = 0
  let logText = ''
  let rowError = false
  let statsBusy = false
  let rssBusy = false
  let tick = 0
  const samplingDeadline = Date.now() + OCR_SAMPLING_TIMEOUT_MS
  while (Date.now() < samplingDeadline) {
    if (tick % 2 === 0) {
      const trigger = runningLogTrigger(row)
      if ((await trigger.count()) > 0) {
        try {
          logText = await readParseLog(page, trigger, PDF_NAME)
        } catch {
          // siatka w trakcie odświeżenia — treść logu z poprzedniej próby pozostaje
        }
      }
      if (renderMs === null && /Skonwertowano \d+ stron/.test(logText)) {
        renderMs = Date.now() - taskStartedAt
      }
      rowError = FAILED.test(await row.innerText().catch(() => ''))
      if (rowError || /OCR stron \d+\/\d+/.test(logText)) break
    }
    if (!statsBusy) {
      statsBusy = true
      fakeStats()
        .then((stats) => {
          if (ocrCount(stats, FAKE_OCR) > 0 && firstOcrMs === null) {
            firstOcrMs = Date.now() - taskStartedAt
          }
        })
        .catch(() => {})
        .finally(() => {
          statsBusy = false
        })
    }
    if (tick % 2 === 0 && !rssBusy) {
      rssBusy = true
      containerStats(workerCid!)
        .then((sample) => {
          if (sample !== null) {
            peakMemBytes = Math.max(peakMemBytes, sample.mem_bytes)
            peakCpuPercent = Math.max(peakCpuPercent, sample.cpu_percent)
          }
        })
        .catch(() => {})
        .finally(() => {
          rssBusy = false
        })
    }
    tick += 1
    await page.waitForTimeout(1_000)
  }
  await page.waitForTimeout(1_500) // domknięcie próbek stats/RSS w locie

  expect(
    rowError,
    `parsowanie nie kończy się błędem${logText ? ` — log: ${logText.slice(-400)}` : ''}`,
  ).toBe(false)
  // (a) pierwsze żądanie fake-ocr ≤ 30 s od startu zadania (potokowość, Q34-10).
  expect(firstOcrMs, 'licznik fake-ocr doszedł do > 0 (a)').not.toBeNull()
  expect(
    firstOcrMs,
    `pierwsze żądanie fake-ocr ≤ 30 s od startu zadania (a): ${firstOcrMs} ms`,
  ).toBeLessThanOrEqual(FIRST_OCR_BUDGET_MS)
  // (b) czas renderu — do wpisu „Skonwertowano N stron (…” (raport, bez twardej asercji czasu).
  expect(renderMs, 'wpis „Skonwertowano … stron” w logu przed etapem OCR (b)').not.toBeNull()
  // Tani koniec: log doszedł do OCR → Stop.
  expect(logText, 'log doszedł do etapu OCR').toMatch(/OCR stron \d+\/\d+/)
  await row.getByRole('button', { name: 'Zatrzymaj parsowanie' }).click()
  await waitForRowText(row, CANCELLED, STOP_BUDGET_MS)
  // (c) szczyt RSS workera ≤ limit kontenera (WD_WORKER_MEM_LIMIT).
  expect(peakMemBytes, 'próbki RSS workera zebrane (c)').toBeGreaterThan(0)
  expect(
    peakMemBytes,
    `szczyt RSS workera ≤ limitu ${Math.round(limitBytes / 1024 ** 2)} MB (c)`,
  ).toBeLessThanOrEqual(limitBytes)

  // Pomiary do raportu TL: adnotacje + stdout + JSON obok real-corpus.json (konwencja WD_REAL_OUT).
  const measurements = {
    scenario: 'SC-E5-H8a-06',
    pdf: PDF_NAME,
    pages: PAGES,
    fake_ocr_delay_ms: 500,
    first_ocr_request_s: round1((firstOcrMs ?? 0) / 1000),
    render_to_converted_s: renderMs === null ? null : round1(renderMs / 1000),
    worker_peak_rss_mb: Math.round(peakMemBytes / 1024 ** 2),
    worker_limit_mb: Math.round(limitBytes / 1024 ** 2),
    worker_peak_cpu_percent: Math.round(peakCpuPercent),
  }
  for (const [key, value] of Object.entries(measurements)) {
    if (key === 'scenario' || key === 'pdf') continue
    test.info().annotations.push({ type: 'pomiar', description: `${key}=${value}` })
  }
  console.log(`[stop-progress] pomiar ${JSON.stringify(measurements)}`)
  if (OUT !== '') {
    mkdirSync(OUT, { recursive: true })
    writeFileSync(
      join(OUT, 'real-stop-progress.json'),
      `${JSON.stringify(measurements, null, 2)}\n`,
    )
  }
})
