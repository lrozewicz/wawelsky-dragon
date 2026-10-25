// Scenariusze E5-H8a (SCENARIOS.md, brief T7): Stop w każdym etapie, postęp co partię i log
// nazywający etap zgodnie z parserem. Scenariusze Stop w trakcie konwersji używają fixture'a
// `multi-batch-960.pdf` (T11: deterministyczny klik Stop przy szybkiej maszynie
// wielordzeniowej), pozostałe — `multi-batch-120.pdf` (120 stron, kontrakt §C7) na stosie
// testowym. Upload PRAWDZIWEGO pliku z dysku przez `DataTransfer` (helpers/dnd.ts),
// nie `setInputFiles`. Linia anulowania w logu to istniejący kontrakt K5
// `HH:MM:SS Task has been cancelled.` (odchyłka TL od BRIEF §Kontrakt, C1) — worker zapisuje
// ją po angielsku, a UI od T3b (SC-V12-06) tłumaczy log na język profilu (PL domyślnie,
// serverMessages.ts wg P1–P29); asercje poniżej celują w brzmienie PL widziane przez
// użytkownika, „vision finished” (poza tabelą) zostaje dosłowne.
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

import { expect, resetDb, test } from './fixtures'
import { POLL_TIMEOUT_MS, apiLogin, createDataset, loginViaUi } from './helpers'
import { dropFile } from './helpers/dnd'
import { expectNoLayoutDefects } from './helpers/layout'
import {
  fakeStats,
  ocrCount,
  registerFakeOcrModel,
  resetFakeStats,
  setOcrDelay,
  setVisionParser,
} from './helpers/ocr'
import type { Page } from '@playwright/test'

// Linia anulowania w logu zadania (K5): worker zapisuje „HH:MM:SS Task has been cancelled.”,
// UI tłumaczy na „HH:MM:SS Zadanie anulowane.” (P17) — OSTATNI wpis, po nim brak wpisów
// konwersji/OCR/embeddingu (odchyłka TL 2026-10-11, CONTRACT.md C1).
const CANCEL_LINE = /\d\d:\d\d:\d\d Zadanie anulowane\.$/

const PDF_NAME = 'multi-batch-120.pdf'
/** Fixture scenariuszy Stop w trakcie konwersji (T11): 960 stron = 39 partii po 25 stron;
 * konwersja trwa ~18 s na maszynie 32-rdzeniowej (pomiar T11), więc klik „natychmiast po
 * pierwszym procencie” (≤ 3 s + odświeżanie wiersza co 3 s) ląduje w konwersji z zapasem ~3,5×.
 * Fixture 120 stron konwertuje się tu w ~7 s — UI widziało wtedy 1 wartość procentu, a Stop
 * trafiał po konwersji (verify-full 2026-10-11, dwa czerwone podejścia). */
const STOP_PDF_NAME = 'multi-batch-960.pdf'
const STOP_PARSE_TOTAL = 960
const FAKE_OCR = 'fake-ocr'

/** Selektory komórki statusu — CSS jak w s03b (popover komórki nie jest modalny, ale siatka
 * DataGrid renderuje wiersze poza drzewem ról, więc `getByRole('row')` bywa zawodne). */
const STATUS_LOG = '[data-testid^="status-log-"]'
const STATUS_STOP = '[data-testid^="status-stop-"]'
const STATUS_PARSE = '[data-testid^="status-parse-"]'

/** Budżet Stop → „Anulowano” na stosie testowym (SCENARIOS.md, warianty). */
const STOP_BUDGET_MS = 15_000
/** Pełne parsowanie fixture'a 120 stron: konwersja ~7 s + chunki + embedding (pomiar T11
 * na 32 rdzeniach: całość 14 s). */
const PARSE_TIMEOUT_MS = 180_000
/** Pełne parsowanie fixture'a 960 stron (T11): pomiar na 32 rdzeniach 35 s; maszyna 3×
 * wolniejsza ~105 s — budżet z zapasem ~3×. */
const PARSE960_TIMEOUT_MS = 300_000

const sleep = (ms: number): Promise<void> => new Promise((resolve) => setTimeout(resolve, ms))

/** Bajty fixture'a z dysku — ten sam plik czyta Node i wstrzykuje do `File` na stronie. */
function pdfBytes(name: string): Buffer {
  return readFileSync(fileURLToPath(new URL(`./fixtures/${name}`, import.meta.url)))
}

/**
 * Tworzy dataset (domyślnie parser DeepDOC), loguje przez UI i otwiera zakładkę Pliki.
 * Do parsera `fake-ocr` służy `setVisionParser` po `registerFakeOcrModel` (reset K9 zasiewa
 * tylko `fake-vision`).
 */
async function openFilesTab(
  page: Page,
  request: Parameters<typeof apiLogin>[0],
  datasetName: string,
): Promise<void> {
  const token = await apiLogin(request)
  const datasetId = await createDataset(request, token, datasetName)
  await loginViaUi(page)
  await page.goto(`/dataset/files/${datasetId}`)
  await expect(page.getByRole('heading', { name: datasetName })).toBeVisible()
}

/** Wgrywa fixture przez strefę drop dialogu z „Parsuj po przesłaniu” i zamyka dialog. */
async function uploadPdfForParse(page: Page, name: string = PDF_NAME): Promise<void> {
  await page.getByTestId('files-add').click()
  const dialog = page.getByRole('dialog')
  await expect(dialog).toBeVisible()
  await dropFile(page, page.getByTestId('upload-dropzone'), pdfBytes(name), name, 'application/pdf')
  await expect(dialog.getByText(name)).toBeVisible()
  await expect(page.getByTestId('upload-parse-toggle')).toBeChecked()
  await page.getByTestId('upload-start').click()
  await expect(dialog.getByText('Przesłano', { exact: true })).toBeVisible({ timeout: 60_000 })
  await expect(page.getByTestId('upload-start')).toBeDisabled({ timeout: POLL_TIMEOUT_MS }) // po sukcesie T15b
  await dialog.getByRole('button', { name: 'Gotowe' }).click()
  await expect(dialog).toBeHidden()
}

/**
 * Otwiera dialog „Log parsowania” klikiem w tekst/chip statusu i zwraca treść bloku logu.
 * Przy pustym `progress_msg` dialog pokazuje „Brak logu” bez bloku `pre` (T4) — wtedy log jest pusty.
 */
async function taskLog(page: Page): Promise<string> {
  await page.locator(STATUS_LOG).click()
  const dialog = page.getByRole('dialog')
  await expect(dialog, 'dialog logu parsowania').toBeVisible()
  const block = dialog.locator('pre')
  const text = (await block.count()) > 0 ? ((await block.textContent()) ?? '') : ''
  await dialog.getByRole('button', { name: 'Zamknij' }).click()
  await expect(dialog).toBeHidden()
  return text
}

/** Niepuste wiersze logu zadania. */
function logLines(log: string): string[] {
  return log.split('\n').filter((line) => line.trim() !== '')
}

/** Liczba z tekstu statusu („12%”); -1, gdy tekst nie jest procentem (np. chip „W kolejce”). */
function rowPercent(text: string): number {
  const match = /(\d+)\s*%/.exec(text)
  return match === null ? -1 : Number(match[1]!)
}

/** Liczniki „d” z wpisów logu „Konwertowanie stron d/N” (P4; T11: wzrost postępu konwersji z logu). */
function batchDoneValues(lines: string[], total: number): number[] {
  const pattern = new RegExp(`Konwertowanie stron (\\d+)/${total}(?:\\D|$)`)
  return lines
    .map((line) => pattern.exec(line))
    .filter((match): match is RegExpExecArray => match !== null)
    .map((match) => Number(match[1]!))
}

/**
 * Opóźnienie fake-ocr to stan USŁUGI (przeżywa reset bazy K9) — test, które je ustawi,
 * sprząta w `afterEach`, żeby nie spowalniać kolejnych scenariuszy.
 */
let fakeOcrDelaySet = false

test.afterEach(async ({ request }) => {
  if (fakeOcrDelaySet) {
    await setOcrDelay(request, 0)
    await resetFakeStats(request)
    fakeOcrDelaySet = false
  }
})

test('SC-E5-H8a-01: Stop w trakcie konwersji (DeepDOC) — „Anulowano” ≤ 15 s, log, ponowne „Parsuj”', async ({
  page,
  request,
}) => {
  test.setTimeout(480_000)

  await resetDb(request)
  await openFilesTab(page, request, 'E2E SC-E5-H8a-01 Stop DeepDOC')
  await uploadPdfForParse(page, STOP_PDF_NAME)

  // Krok 1: wiersz pokazuje procent postępu ≥ 2 (SCENARIOS: „postęp > 0”). ⊗ klikamy
  // NATYCHMIAST po tym progu (T11): wiersz odświeża się co 3 s, więc czekanie na drugą
  // wartość procentu na szybkiej maszynie przegrywa wyścig z „Sukces” (verify-full
  // 2026-10-11). Próg to 2, nie > 0: „1%” to zgłoszenie zadania („Zadanie przyjęte.”, P1
  // @ PROGRESS_START=0.01, ingest_pipeline.py) PRZED pierwszą partią — klik przy „1%” może
  // anulować z jednym wpisem konwersji w logu. Pierwsza partia 960 stron to 24/960 → 2%.
  // Że konwersja FAKTYCZNIE postępowała, asertujemy z logu w kroku 3.
  const status = page.locator(STATUS_LOG)
  await status.waitFor({ state: 'visible', timeout: POLL_TIMEOUT_MS })
  await expect
    .poll(async () => rowPercent((await status.textContent()) ?? ''), {
      message: 'wiersz pokazuje procent postępu ≥ 2 (≥ 1 ukończona partia)',
      timeout: POLL_TIMEOUT_MS,
    })
    .toBeGreaterThanOrEqual(2)

  // Krok 2: ⊗ Stop w trakcie konwersji → „Anulowano” ≤ 15 s (stos testowy).
  await page.locator(STATUS_STOP).click()
  await expect(page.locator(STATUS_LOG), 'status po Stop').toHaveText('Anulowano', {
    timeout: STOP_BUDGET_MS,
  })

  // Krok 3: ostatni wpis logu mówi o anulowaniu (K5); konwersja postępowała — ≥ 2 wpisy
  // „Konwertowanie stron d/960” z RÓŻNYMI licznikami stron (T11: wzrost procentu z logu zamiast
  // z próbkowania wiersza). Po anulowaniu brak nowych wpisów — log czytany DRUGI raz po ~3 s,
  // żeby wykluczyć dobiegające wpisy konwersji/OCR/embeddingu.
  const lines = logLines(await taskLog(page))
  expect(lines.length, 'log zadania niepusty').toBeGreaterThan(0)
  expect(lines[lines.length - 1], 'ostatni wpis logu po Stop').toMatch(CANCEL_LINE)
  const converted = batchDoneValues(lines, STOP_PARSE_TOTAL)
  expect(
    converted.length,
    'wpisy „Konwertowanie stron d/960” (Stop padł w trakcie konwersji)',
  ).toBeGreaterThanOrEqual(2)
  expect(
    new Set(converted).size,
    'licznik stron konwersji rósł (≥ 2 różne wartości)',
  ).toBeGreaterThanOrEqual(2)
  await sleep(3_000)
  const linesAfterSettle = logLines(await taskLog(page))
  expect(
    linesAfterSettle[linesAfterSettle.length - 1],
    'brak nowych wpisów logu po linii anulowania (odczyt drugi po ~3 s)',
  ).toBe(lines[lines.length - 1])

  // Krok 4: ponowne „Parsuj” → parsowanie od zera kończy się „Sukces”.
  await page.locator(STATUS_PARSE).click()
  const confirm = page.getByTestId('reparse-confirm')
  if (await confirm.isVisible()) await confirm.click()
  await expect(page.locator(STATUS_LOG), 'status po ponownym parsowaniu').toHaveText('Sukces', {
    timeout: PARSE960_TIMEOUT_MS,
  })
})

test('SC-E5-H8a-01 wariant F5: odświeżenie w trakcie — postęp widoczny dalej, Stop działa', async ({
  page,
  request,
}) => {
  test.setTimeout(300_000)

  await resetDb(request)
  await openFilesTab(page, request, 'E2E SC-E5-H8a-01 F5')
  await uploadPdfForParse(page, STOP_PDF_NAME)

  // ⊗ klikamy natychmiast po procencie ≥ 2 (T11 — patrz SC-E5-H8a-01: „1%” to zgłoszenie
  // zadania przed pierwszą partią).
  const status = page.locator(STATUS_LOG)
  await status.waitFor({ state: 'visible', timeout: POLL_TIMEOUT_MS })
  await expect
    .poll(async () => rowPercent((await status.textContent()) ?? ''), {
      message: 'wiersz pokazuje procent postępu ≥ 2 (≥ 1 ukończona partia)',
      timeout: POLL_TIMEOUT_MS,
    })
    .toBeGreaterThanOrEqual(2)

  // F5 w trakcie konwersji: procent postępu widoczny dalej.
  await page.reload()
  await expect(page.locator(STATUS_LOG), 'procent po odświeżeniu').toHaveText(/\d+\s*%/, {
    timeout: POLL_TIMEOUT_MS,
  })

  // Stop działa po F5 → „Anulowano” ≤ 15 s, a log kończy się linią anulowania (K5).
  await page.locator(STATUS_STOP).click()
  await expect(page.locator(STATUS_LOG), 'status po Stop po F5').toHaveText('Anulowano', {
    timeout: STOP_BUDGET_MS,
  })
  const lines = logLines(await taskLog(page))
  expect(lines[lines.length - 1], 'ostatni wpis logu po Stop po F5').toMatch(CANCEL_LINE)
})

test('SC-E5-H8a-01 wariant podwójny Stop: jedno anulowanie, brak komunikatu błędu', async ({
  page,
  request,
}) => {
  test.setTimeout(300_000)

  await resetDb(request)
  await openFilesTab(page, request, 'E2E SC-E5-H8a-01 podwójny Stop')
  await uploadPdfForParse(page, STOP_PDF_NAME)

  // ⊗ klikamy natychmiast po procencie ≥ 2 (T11 — patrz SC-E5-H8a-01: „1%” to zgłoszenie
  // zadania przed pierwszą partią).
  const status = page.locator(STATUS_LOG)
  await status.waitFor({ state: 'visible', timeout: POLL_TIMEOUT_MS })
  await expect
    .poll(async () => rowPercent((await status.textContent()) ?? ''), {
      message: 'wiersz pokazuje procent postępu ≥ 2 (≥ 1 ukończona partia)',
      timeout: POLL_TIMEOUT_MS,
    })
    .toBeGreaterThanOrEqual(2)

  // Podwójny klik ⊗ — drugi klik nie może zepsuć zadania ani zgłosić błędu. Drugi klik jest
  // best-effort: gdy pierwsze anulowanie zaskoczy natychmiast, ⊗ znika z wiersza i klik nie ma
  // na co trafić (powtórka przez `catch` — brak przycisku to oczekiwany przebieg, nie błąd testu).
  const stop = page.locator(STATUS_STOP)
  await stop.click()
  await stop.click({ timeout: 2_000 }).catch(() => {})

  await expect(page.locator(STATUS_LOG), 'status po podwójnym Stop').toHaveText('Anulowano', {
    timeout: STOP_BUDGET_MS,
  })
  await expect(page.getByRole('alert'), 'brak komunikatu błędu po drugim klikiem').toHaveCount(0)

  // Dokładnie JEDEN wpis o anulowaniu i to on jest ostatni w logu.
  const lines = logLines(await taskLog(page))
  const cancelLines = lines.filter((line) => CANCEL_LINE.test(line))
  expect(cancelLines, 'jedno anulowanie w logu').toHaveLength(1)
  expect(lines[lines.length - 1], 'anulowanie jako ostatni wpis').toBe(cancelLines[0])
})

test.describe('SC-E5-H8a-01 wariant 390 px', () => {
  test.use({ viewport: { width: 390, height: 844 } })

  test('status i Stop widoczne w wierszu, brak wad układu, Stop → „Anulowano”', async ({
    page,
    request,
  }) => {
    test.setTimeout(300_000)

    await resetDb(request)
    await openFilesTab(page, request, 'E2E SC-E5-H8a-01 mobile')
    await uploadPdfForParse(page, STOP_PDF_NAME)

    // ⊗ klikamy natychmiast po procencie ≥ 2 (T11 — patrz SC-E5-H8a-01: „1%” to zgłoszenie
    // zadania przed pierwszą partią).
    const status = page.locator(STATUS_LOG)
    await status.waitFor({ state: 'visible', timeout: POLL_TIMEOUT_MS })
    await expect
      .poll(async () => rowPercent((await status.textContent()) ?? ''), {
        message: 'wiersz pokazuje procent postępu ≥ 2 (≥ 1 ukończona partia)',
        timeout: POLL_TIMEOUT_MS,
      })
      .toBeGreaterThanOrEqual(2)

    // Status i ⊗ w wierszu osiągalne na ekranie telefonu (po przewinięciu siatki).
    const stop = page.locator(STATUS_STOP)
    await stop.scrollIntoViewIfNeeded()
    await expect(status, 'procent widoczny na 390 px').toBeInViewport()
    await expect(stop, 'Stop widoczny na 390 px').toBeInViewport()
    await expectNoLayoutDefects(page, 'SC-E5-H8a-01 390 px wiersz w trakcie parsowania')

    await stop.click()
    await expect(page.locator(STATUS_LOG), 'status po Stop na 390 px').toHaveText('Anulowano', {
      timeout: STOP_BUDGET_MS,
    })
    await expectNoLayoutDefects(page, 'SC-E5-H8a-01 390 px po zatrzymaniu')

    const lines = logLines(await taskLog(page))
    expect(lines[lines.length - 1], 'ostatni wpis logu po Stop (390 px)').toMatch(CANCEL_LINE)
  })
})

test('SC-E5-H8a-02: Stop w trakcie OCR (fake-ocr 1200 ms/stronę) — licznik zamiera po anulowaniu', async ({
  page,
  request,
}) => {
  test.setTimeout(300_000)

  await resetDb(request)
  const token = await apiLogin(request)
  await registerFakeOcrModel(request, token)
  const datasetId = await createDataset(request, token, 'E2E SC-E5-H8a-02 Stop OCR')
  await setVisionParser(request, token, datasetId, FAKE_OCR)

  fakeOcrDelaySet = true
  // 1200 ms/stronę (pierwotnie 400): potokowe OCR (T5) rozpoznaje kilka stron równolegle,
  // więc przy 400 ms cały etap trwał ~12 s — za krótko na pewne kliknięcie Stop w jego trakcie
  // (SCENARIOS: „etapy trwały dość długo na kliknięcie Stop”). Przy ~4 stronach naraz etap
  // trwa ~36 s.
  await setOcrDelay(request, 1200)
  await resetFakeStats(request)

  await loginViaUi(page)
  await page.goto(`/dataset/files/${datasetId}`)
  await expect(page.getByRole('heading', { name: 'E2E SC-E5-H8a-02 Stop OCR' })).toBeVisible()
  await uploadPdfForParse(page)

  // Krok 1: etap OCR widoczny w logu zadania — „OCR stron n/120 (fake-ocr)” (P7). Podpowiedź
  // komórki zamyka się przy rerenderze siatki (wymiana DOM komórki przy odświeżaniu) i nie
  // otwiera ponownie dla kursora nieruchomego (sonda T9: tooltips=0 mimo powtarzanych
  // hoverów), więc poll czyta DIALOG logu: każde otwarcie snapshotuje bieżący progress_msg.
  await page.locator(STATUS_LOG).waitFor({ state: 'visible', timeout: POLL_TIMEOUT_MS })
  await expect
    .poll(async () => /OCR stron \d+\/120 \(fake-ocr\)/.test(await taskLog(page)), {
      message: 'log pokazuje licznik stron OCR z nazwą modelu',
      timeout: 120_000,
    })
    .toBe(true)

  // Krok 2: Stop w trakcie OCR; odczyt licznika w chwili kliknięcia.
  const atStop = ocrCount(await fakeStats(request), FAKE_OCR)
  await page.locator(STATUS_STOP).click()
  await expect(page.locator(STATUS_LOG), 'status po Stop w OCR').toHaveText('Anulowano', {
    timeout: STOP_BUDGET_MS,
  })

  // Po „Anulowano” licznik fake-ocr stoi: dwa odczyty w odstępie 3 s identyczne, najwyżej +3
  // względem chwili kliknięcia (zapytania już wysłane — współbieżność).
  const first = ocrCount(await fakeStats(request), FAKE_OCR)
  await sleep(3_000)
  const second = ocrCount(await fakeStats(request), FAKE_OCR)
  expect(second, 'licznik fake-ocr nie rośnie po anulowaniu').toBe(first)
  expect(first, 'licznik ≤ odczyt ze Stop + współbieżność').toBeLessThanOrEqual(atStop + 3)
})

test('SC-E5-H8a-04: postęp konwersji zmienia się, log ma liczniki partii i chunków', async ({
  page,
  request,
}) => {
  test.setTimeout(300_000)

  await resetDb(request)
  await openFilesTab(page, request, 'E2E SC-E5-H8a-04 postęp')
  await uploadPdfForParse(page)

  // Pętla aż do końca parsowania (pilnuje też, by nie było „Błąd”). Wzrost procentu
  // asertujemy z LOGU (T11): na szybkiej maszynie (32 rdzenie, konwersja ~7 s) wiersz
  // odświeżany co 3 s pokazuje 1 wartość procentu zanim status zmieni się na „Sukces”,
  // a wpisy „Konwertowanie stron d/120” w logu kumulują się niezależnie od tempa UI.
  let succeeded = false
  const deadline = Date.now() + PARSE_TIMEOUT_MS
  while (Date.now() < deadline) {
    const text = (
      (await page
        .locator(STATUS_LOG)
        .textContent()
        .catch(() => null)) ?? ''
    ).trim()
    if (text === 'Sukces') {
      succeeded = true
      break
    }
    expect(text, 'parsowanie nie kończy się błędem').not.toBe('Błąd')
    await sleep(1_000)
  }
  expect(succeeded, 'parsowanie dochodzi do „Sukces”').toBe(true)

  // Log zadania: licznik stron co partię i jego WZROST (sedno scenariusza „postęp zmienia
  // się” — rośnie, nie stoi na „1%”), liczba chunków i postęp embeddingu.
  const log = await taskLog(page)
  const converting = log.match(/Konwertowanie stron \d+\/120/g) ?? []
  expect(converting.length, 'wpisy „Konwertowanie stron d/120” (co partię)').toBeGreaterThanOrEqual(
    3,
  )
  const doneValues = batchDoneValues(logLines(log), 120)
  expect(
    new Set(doneValues).size,
    'licznik stron konwersji rósł (≥ 2 różne wartości)',
  ).toBeGreaterThanOrEqual(2)
  expect(log, 'liczba chunków').toMatch(/Generowanie \d+ fragmentów/)
  expect(log, 'postęp embeddingu').toMatch(/Osadzanie fragmentów \(\d+\/\d+\)/)
})

test('SC-E5-H8a-05 a: log DeepDOC nazywa etap tekstu, bez „vision finished”', async ({
  page,
  request,
}) => {
  test.setTimeout(300_000)

  await resetDb(request)
  await openFilesTab(page, request, 'E2E SC-E5-H8a-05 DeepDOC')
  await uploadPdfForParse(page)

  await expect(page.locator(STATUS_LOG), 'parsowanie do „Sukces”').toHaveText('Sukces', {
    timeout: PARSE_TIMEOUT_MS,
  })

  const log = await taskLog(page)
  expect(log, 'wpis o konwersji warstwy tekstowej').toContain(
    'Skonwertowano 120 stron (warstwa tekstowa)',
  )
  // „vision finished” jest poza tabelą P1–P29, więc UI pokazuje je dosłownie także w PL.
  expect(log, 'bez etykiety wizji dla parsera tekstowego').not.toContain('vision finished')
})

test('SC-E5-H8a-05 b: log fake-ocr nazywa model i liczbę stron', async ({ page, request }) => {
  test.setTimeout(300_000)

  await resetDb(request)
  const token = await apiLogin(request)
  await registerFakeOcrModel(request, token)
  const datasetId = await createDataset(request, token, 'E2E SC-E5-H8a-05 fake-ocr')
  await setVisionParser(request, token, datasetId, FAKE_OCR)
  await setOcrDelay(request, 0)

  await loginViaUi(page)
  await page.goto(`/dataset/files/${datasetId}`)
  await expect(page.getByRole('heading', { name: 'E2E SC-E5-H8a-05 fake-ocr' })).toBeVisible()
  await uploadPdfForParse(page)

  await expect(page.locator(STATUS_LOG), 'parsowanie do „Sukces”').toHaveText('Sukces', {
    timeout: PARSE_TIMEOUT_MS,
  })

  const log = await taskLog(page)
  expect(log, 'koniec OCR z nazwą modelu i liczbą stron').toContain(
    `OCR zakończone: 120 stron (${FAKE_OCR})`,
  )
})
