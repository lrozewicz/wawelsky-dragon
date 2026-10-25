// Scenariusz SC-E7-2-06 (WP E7-2 T9; biblioteka regresji docs/scenarios/eksport-import.md R-KB-01
// kroki 1–8): transfer bazy wiedzy A → B na DWOCH stosach clean-install. Fazy wybiera
// `WD_KBAB_PHASE` (ustawia tools/dev/kb-transfer-ab.sh, jedno clean-install na fazę):
//   export — stos A: logowanie formularzem, baza z rocznikiem GUS (fallback fixture
//   multi-batch-120.pdf jak w mcp-prod.spec.ts) i DOCX, parsowanie do „Sukces”, edycja treści
//   jednego chunku (unikalny znacznik) i wyłączenie innego w UI, eksport ⋮ → dialog → pasek
//   „Gotowe” → „Pobierz”; paczka `package.wdkb.zip` i `state.json` lądują w `$WD_KBAB_DIR`.
//   import — świeży stos B: import paczki w UI (podsumowanie → pasek „Gotowe” → „Otwórz”), pliki
//   obecne, znacznik i wyłączenie zachowane, test retrievalu na pytaniu z state.json zwraca cytat
//   (źródło z pliku bazy), a wyłączony chunk nie ma jej w wynikach (asercja precyzyjna przez API —
//   pełna treść bez okna podświetlenia; wzór mcp-prod.spec.ts).
// Stos i konto wstrzykuje clean-install.sh (WD_CI_*); bez seedu K9 i bez SQL — konwencja e2e-real.
// Selektory jak użytkownik (role/etykiety/tekst); jedyny `data-testid` to pasek zadań z CONTRACT
// E7-2 §7 (`kb-task-row` + `data-task-kind`/`data-task-status`).
import { existsSync, readFileSync, writeFileSync } from 'node:fs'
import { basename, join } from 'node:path'
import { fileURLToPath } from 'node:url'

import { expect, test } from '@playwright/test'
import type { Locator, Page } from '@playwright/test'

// --- konfiguracja biegu (wstrzykiwana przez kb-transfer-ab.sh + clean-install.sh) ---
const PHASE = process.env.WD_KBAB_PHASE ?? ''
const OUT_DIR = process.env.WD_KBAB_DIR ?? ''
const ADMIN_EMAIL = process.env.WD_CI_ADMIN_EMAIL ?? ''
const ADMIN_PASSWORD = process.env.WD_CI_ADMIN_PASSWORD ?? ''
const CORPUS = process.env.WD_REAL_CORPUS ?? ''

// Nazwa bazy przechodzi przez paczkę (state.json) — na świeżym stosie B jest wolna.
const DATASET_NAME = 'E7-2 transfer AB'
const GUS_PDF_NAME = 'gus_rocznik_statystyczny_rp_2024.pdf'
const NCBR_DOCX_NAME = 'wzor_raportu_okresowego_ncbr.docx'
// Fallback korpusu jak w mcp-prod.spec.ts: brak rocznika → fixture z repo (120 stron).
const FIXTURE_PDF = fileURLToPath(new URL('../e2e/fixtures/multi-batch-120.pdf', import.meta.url))

// Unikalny znacznik edycji treści chunku (brief T9); w fazie import przychodzi ze state.json.
const MARKER = `E7-2-EDYTOWANY-${Date.now()}`

// Limity (brief T9): parsowanie per plik jak w real-corpus.spec.ts (1200 s); eksport i import
// zadania ≤ 3 min (z zapasem — jak budżety E7-1); faza importu 600 s na test (brief).
const PARSE_LIMIT_MS = 1_200_000
const TASK_BUDGET_MS = 360_000
const UI_TIMEOUT_MS = 60_000

/** Logowanie formularzem `/login` kontem administracyjnym czystej instalacji (wzór clean-install). */
async function loginAsAdmin(page: Page): Promise<void> {
  await page.goto('/login')
  await page.getByLabel('E-mail').fill(ADMIN_EMAIL)
  // `exact` — inaczej `getByLabel('Hasło')` trafia też w przycisk „Pokaż hasło” (wzór clean-install).
  await page.getByLabel('Hasło', { exact: true }).fill(ADMIN_PASSWORD)
  await page.getByRole('button', { name: 'Zaloguj się' }).click()
  await expect(
    page.getByRole('navigation').getByRole('link', { name: 'Bazy wiedzy' }),
  ).toBeVisible()
}

/** Wiersz siatki plików dokumentu o danej nazwie (wzór real-corpus.spec.ts). */
function documentRow(page: Page, name: string): Locator {
  return page.getByRole('row').filter({ hasText: name })
}

/** Wiersz paska zadań danego rodzaju i nazwy bazy (CONTRACT E7-2 §7: data-testid + data-task-kind). */
function taskRow(page: Page, kind: 'export' | 'import', name: string): Locator {
  return page
    .locator(`[data-testid="kb-task-row"][data-task-kind="${kind}"]`)
    .filter({ hasText: name })
}

/** Karty chunków (role=group z przełącznikiem dostępności — bez data-testid, jak użytkownik). */
function chunkCards(page: Page): Locator {
  return page.getByRole('group').filter({
    has: page.getByRole('switch', { name: 'Chunk włączony' }),
  })
}

/** Karty chunków tekstowych (chip typu „Tekst”); tabele/obrazy pomijamy — ich treść renderuje się inaczej. */
function textChunkCards(page: Page): Locator {
  return chunkCards(page).filter({ has: page.getByText('Tekst', { exact: true }) })
}

/**
 * Pełna treść chunku z dialogu edycji (pole „Treść” — bez przycięcia karty do 4 linii); dialog
 * zamykany „Anuluj” — read-only.
 */
async function readChunkContent(page: Page, card: Locator): Promise<string> {
  await card.getByRole('button', { name: 'Edytuj' }).click()
  const dialog = page.getByRole('dialog', { name: 'Edytuj chunk' })
  await expect(dialog).toBeVisible()
  const content = await dialog.getByLabel('Treść').inputValue()
  await dialog.getByRole('button', { name: 'Anuluj' }).click()
  await expect(dialog).toBeHidden()
  return content
}

/** Zapis treści chunku w dialogu edycji (przycisk „Zapisz”). */
async function editChunkContent(page: Page, card: Locator, content: string): Promise<void> {
  await card.getByRole('button', { name: 'Edytuj' }).click()
  const dialog = page.getByRole('dialog', { name: 'Edytuj chunk' })
  await expect(dialog).toBeVisible()
  await dialog.getByLabel('Treść').fill(content)
  await dialog.getByRole('button', { name: 'Zapisz' }).click()
  await expect(dialog).toBeHidden()
}

/**
 * Pytanie testu retrievalu z treści chunku: pierwsze zdanie pierwszej niepustej linii (fake-embed
 * jest deterministyczny — pytanie dosłownie z treści daje trafienie, wzór mcp-prod.spec.ts).
 * Za krótkie zdanie zastępujemy wycinkiem treści.
 */
function questionFrom(content: string): string {
  for (const raw of content.split('\n')) {
    const line = raw.trim()
    if (line === '') continue
    const sentence = line.split(/(?<=[.!?])\s+/)[0]?.trim() ?? ''
    return sentence.length >= 12 ? sentence : content.slice(0, 150)
  }
  return content.slice(0, 150)
}

/**
 * Rozpoznawalny prefiks treści wyłączonego chunku (state.json → UI i API). Pierwsza linia bez
 * HTML-a (markdown renderuje `<fcel>` itp. jako pominięte tagi — treść karty musiałaby być uboższa
 * od surowej); fallback: surowy wycinek 120 znaków.
 */
function disabledTextOf(content: string): string {
  for (const line of content.split('\n')) {
    const trimmed = line.trim()
    if (trimmed !== '' && !trimmed.includes('<')) return trimmed.slice(0, 120)
  }
  return content.slice(0, 120)
}

// Fazy dzielą stos na dwa biegi clean-install, ale w ramach biegu kolejność jest istotna
// (konwencja e2e-real: serial jak w real-corpus.spec.ts / mcp-prod.spec.ts).
test.describe.configure({ mode: 'serial' })

test('SC-E7-2-06 faza export: stos A — baza (GUS + DOCX), edycja i wyłączenie chunku, eksport w UI', async ({
  page,
}) => {
  test.skip(
    PHASE !== 'export',
    'bieg 1 uruchamia tools/dev/kb-transfer-ab.sh z WD_KBAB_PHASE=export',
  )
  // Budżet fazy (brief T9: 600 s) + okno parsowania jak w real-corpus.spec.ts (1200 s per plik);
  // jeden setTimeout, bo deadline Playwrighta liczony jest od startu testu (lib/worker testInfo).
  test.setTimeout(600_000 + PARSE_LIMIT_MS)
  expect(OUT_DIR, 'WD_KBAB_DIR od kb-transfer-ab.sh').not.toBe('')
  expect(CORPUS, 'WD_REAL_CORPUS od kb-transfer-ab.sh').not.toBe('')

  // 1. Logowanie formularzem `/login` (wzór clean-install.spec.ts).
  await loginAsAdmin(page)
  const nav = page.getByRole('navigation')

  // 2. Baza domyślnym modelem embeddingu (pole nie ruszane — jak clean-install).
  await nav.getByRole('link', { name: 'Bazy wiedzy' }).click()
  await expect(page).toHaveURL(/\/datasets$/)
  await page.getByRole('button', { name: 'Utwórz dataset' }).first().click()
  const createDialog = page.getByRole('dialog')
  await expect(createDialog).toBeVisible()
  await createDialog.getByLabel('Nazwa').fill(DATASET_NAME)
  await createDialog.getByRole('button', { name: 'Utwórz' }).click()
  await expect(page.getByRole('heading', { name: DATASET_NAME })).toBeVisible()

  // 3. Upload rocznika GUS (fallback fixture jak w mcp-prod.spec.ts) i DOCX z parsowaniem po
  //    przesłaniu; oba pliki przez jedno okno wyboru (GUS ≥ 12 MB i tak wymaga choosera).
  const pdfPath = `${CORPUS}/pdf/${GUS_PDF_NAME}`
  const docxPath = `${CORPUS}/docx/${NCBR_DOCX_NAME}`
  expect(existsSync(docxPath), `korpus: brak pliku ${docxPath}`).toBe(true)
  const pdfUsed = existsSync(pdfPath) ? pdfPath : FIXTURE_PDF
  const pdfName = basename(pdfUsed)
  await page.getByRole('button', { name: 'Prześlij plik' }).click()
  const uploadDialog = page.getByRole('dialog')
  await expect(uploadDialog.getByRole('heading', { name: 'Prześlij pliki' })).toBeVisible()
  await expect(uploadDialog.getByRole('switch', { name: 'Parsuj po przesłaniu' })).toBeChecked()
  const chooser = page.waitForEvent('filechooser')
  await uploadDialog.getByRole('button', { name: 'Wybierz pliki' }).click()
  await (await chooser).setFiles([pdfUsed, docxPath])
  await uploadDialog.getByRole('button', { name: 'Prześlij' }).click()
  await expect
    .poll(async () => uploadDialog.getByText('Przesłano', { exact: true }).count(), {
      timeout: 300_000,
    })
    .toBe(2)
  await uploadDialog.getByRole('button', { name: 'Gotowe' }).click()

  // 4. Parsowanie obu plików do „Sukces” (limit per plik jak w real-corpus.spec.ts).
  const pdfRow = documentRow(page, pdfName)
  const docxRow = documentRow(page, NCBR_DOCX_NAME)
  await Promise.all([
    expect(pdfRow.getByText('Sukces', { exact: true })).toBeVisible({ timeout: PARSE_LIMIT_MS }),
    expect(docxRow.getByText('Sukces', { exact: true })).toBeVisible({ timeout: PARSE_LIMIT_MS }),
  ])

  // 5. Strona chunków dokumentu PDF (klik w nazwę pliku — wzór real-corpus „ui”).
  await pdfRow.getByRole('link', { name: pdfName, exact: true }).click()
  await expect(page).toHaveURL(/\/chunk\/parsed\/chunks/)
  await expect(page.getByRole('heading', { name: 'Wynik chunkowania' })).toBeVisible({
    timeout: UI_TIMEOUT_MS,
  })
  const textCards = textChunkCards(page)
  await expect(textCards.nth(2)).toBeVisible({ timeout: UI_TIMEOUT_MS })

  // 6. Treści chunków z dialogu edycji (pełna treść, bez mutacji): znacznik dostanie pierwszy,
  //    wyłączenie — drugi, pytanie retrievalu — trzeci (nie ruszany w ogóle).
  const editedOriginal = await readChunkContent(page, textCards.nth(0))
  const disabledText = disabledTextOf(await readChunkContent(page, textCards.nth(1)))
  const question = questionFrom(await readChunkContent(page, textCards.nth(2)))
  expect(question.length, 'pytanie retrievalu z treści chunku').toBeGreaterThan(0)

  // 7a. Edycja treści: oryginał + unikalny znacznik (R-KB-01 krok 3); znacznik widoczny na karcie.
  await editChunkContent(page, textCards.nth(0), `${editedOriginal}\n\n${MARKER}`)
  await expect(page.getByText(MARKER).first()).toBeVisible({ timeout: UI_TIMEOUT_MS })

  // 7b. Wyłączenie drugiego chunku przełącznikiem karty (R-KB-01 krok 4).
  const cardsAfterEdit = textChunkCards(page)
  const disableSwitch = cardsAfterEdit.nth(1).getByRole('switch', { name: 'Chunk włączony' })
  await disableSwitch.click()
  await expect(disableSwitch).not.toBeChecked({ timeout: UI_TIMEOUT_MS })

  // 8. Eksport w UI: ⋮ „Eksportuj” → dialog → start → pasek zadań „Gotowe” → „Pobierz” (≤ 3 min).
  //    Zjazd z listy chunków breadcrumbem „Bazy wiedzy” (globalna nawigacja + breadcrumby = dwa
  //    landmarki `navigation` — `page.getByRole('navigation')` byłby niejednoznaczny).
  await page
    .getByRole('navigation', { name: 'Ścieżka nawigacji' })
    .getByRole('link', { name: 'Bazy wiedzy' })
    .click()
  await expect(page).toHaveURL(/\/datasets$/)
  await page.getByRole('button', { name: `Menu bazy wiedzy ${DATASET_NAME}` }).click()
  const menu = page.getByRole('menu')
  await expect(menu.getByRole('menuitem', { name: 'Eksportuj' })).toBeVisible()
  await menu.getByRole('menuitem', { name: 'Eksportuj' }).click()
  const exportDialog = page.getByRole('dialog', { name: `Eksportuj „${DATASET_NAME}”` })
  await expect(exportDialog).toBeVisible()
  await expect(exportDialog.getByText(/2\s*pliki/), '2 pliki w podsumowaniu').toBeVisible()
  await expect(exportDialog.getByText(/Do paczki trafią:/)).toBeVisible()
  await expect(exportDialog.getByRole('switch', { name: 'Dołącz wektory' })).toBeChecked()
  await exportDialog.getByRole('button', { name: 'Eksportuj' }).click()
  await expect(exportDialog).toBeHidden()
  const row = taskRow(page, 'export', DATASET_NAME)
  await expect(row, 'wiersz eksportu w pasku zadań').toBeVisible()
  await expect(row).toHaveAttribute('data-task-status', 'done', { timeout: TASK_BUDGET_MS })
  await expect(row.getByText(/Gotowe · /)).toBeVisible()
  const downloadPromise = page.waitForEvent('download')
  await row.getByRole('button', { name: 'Pobierz' }).click()
  const download = await downloadPromise
  expect(download.suggestedFilename(), 'nazwa pobranej paczki').toMatch(/\.wdkb\.zip$/)
  await download.saveAs(join(OUT_DIR, 'package.wdkb.zip'))

  // 9. state.json — wymiana stanu między biegami przez $WD_KBAB_DIR (brief T9).
  writeFileSync(
    join(OUT_DIR, 'state.json'),
    `${JSON.stringify(
      { editedText: MARKER, disabledText, question, datasetName: DATASET_NAME },
      null,
      2,
    )}\n`,
  )
})

test('SC-E7-2-06 faza import: stos B — import paczki, retrieval z cytatem, edycja i wyłączenie zachowane', async ({
  page,
  request,
}) => {
  test.skip(
    PHASE !== 'import',
    'bieg 2 uruchamia tools/dev/kb-transfer-ab.sh z WD_KBAB_PHASE=import',
  )
  test.setTimeout(600_000) // budżet fazy (brief T9)
  expect(OUT_DIR, 'WD_KBAB_DIR od kb-transfer-ab.sh').not.toBe('')
  const packagePath = join(OUT_DIR, 'package.wdkb.zip')
  const statePath = join(OUT_DIR, 'state.json')
  expect(existsSync(packagePath), `brak paczki z fazy export: ${packagePath}`).toBe(true)
  const state = JSON.parse(readFileSync(statePath, 'utf8')) as {
    editedText: string
    disabledText: string
    question: string
    datasetName: string
  }

  // 1. Logowanie formularzem na świeżym stosie B (ten sam admin czystej instalacji).
  await loginAsAdmin(page)

  // 2. Import paczki: „Importuj” → dialog → „Wybierz plik” → podsumowanie (nazwa z paczki).
  await page.getByRole('navigation').getByRole('link', { name: 'Bazy wiedzy' }).click()
  await expect(page).toHaveURL(/\/datasets$/)
  await page.getByRole('button', { name: 'Importuj' }).click()
  const importDialog = page.getByRole('dialog', { name: 'Importuj bazę wiedzy' })
  await expect(importDialog).toBeVisible()
  const chooser = page.waitForEvent('filechooser')
  await importDialog.getByRole('button', { name: 'Wybierz plik' }).click()
  await (await chooser).setFiles(packagePath)
  const nameField = importDialog.getByLabel('Nazwa', { exact: true })
  await expect(nameField, 'nazwa wypełniona z paczki').toHaveValue(state.datasetName, {
    timeout: 120_000,
  })
  await expect(importDialog.getByText(/2\s*pliki/), '2 pliki w podsumowaniu').toBeVisible()
  await expect(importDialog.getByText('Zgodny z paczką'), 'model zgodny z paczką').toBeVisible()

  // 3. Start importu → pasek zadań „Gotowe” (≤ 3 min) → „Otwórz”.
  await importDialog.getByRole('button', { name: 'Importuj' }).click()
  await expect(importDialog).toBeHidden()
  const row = taskRow(page, 'import', state.datasetName)
  await expect(row, 'wiersz importu w pasku zadań').toBeVisible()
  await expect(row).toHaveAttribute('data-task-status', 'done', { timeout: TASK_BUDGET_MS })
  await expect(row.getByText(/Gotowe — 2 pliki/)).toBeVisible()
  await row.getByRole('button', { name: 'Otwórz' }).click()
  await expect(page).toHaveURL(/\/dataset\/files\//)
  const datasetId = new URL(page.url()).pathname.split('/')[3] ?? ''
  expect(datasetId, 'id datasetu z adresu strony plików').not.toBe('')
  await expect(page.getByRole('heading', { name: state.datasetName })).toBeVisible({
    timeout: UI_TIMEOUT_MS,
  })

  // 4. Pliki obecne i „Sukces” (bez parsowania na B); nazwę PDF czytamy z siatki (fallback z fazy
  //    export mógł użyć fixture'u — stan.json nie niesie nazw plików).
  const pdfRow = page.getByRole('row').filter({ hasText: '.pdf' })
  const docxRow = page.getByRole('row').filter({ hasText: '.docx' })
  await expect(pdfRow).toBeVisible({ timeout: UI_TIMEOUT_MS })
  await expect(docxRow).toBeVisible()
  const pdfName = (await pdfRow.getByRole('link').innerText()).trim()
  await expect(pdfRow.getByText('Sukces', { exact: true })).toBeVisible({ timeout: UI_TIMEOUT_MS })
  await expect(docxRow.getByText('Sukces', { exact: true })).toBeVisible({ timeout: UI_TIMEOUT_MS })

  // 5. Edytowany chunk zawiera znacznik (szukajka strony chunków — filtr serwerowy po treści).
  await pdfRow.getByRole('link', { name: pdfName, exact: true }).click()
  await expect(page).toHaveURL(/\/chunk\/parsed\/chunks/)
  await expect(page.getByRole('heading', { name: 'Wynik chunkowania' })).toBeVisible({
    timeout: UI_TIMEOUT_MS,
  })
  const search = page.getByRole('textbox', { name: 'Szukaj w chunkach' })
  await search.fill(state.editedText)
  await expect(chunkCards(page)).toHaveCount(1, { timeout: UI_TIMEOUT_MS })
  await expect(chunkCards(page).first()).toContainText(state.editedText)

  // 6. Wyłączony chunk ma stan wyłączony (filtr „Wyłączone” — dokładnie ten jeden chunk).
  await search.fill('')
  await page.getByRole('button', { name: 'Wyłączone' }).click()
  await expect(chunkCards(page)).toHaveCount(1, { timeout: UI_TIMEOUT_MS })
  await expect(chunkCards(page).first()).toContainText(state.disabledText)
  await expect(
    chunkCards(page).first().getByRole('switch', { name: 'Chunk włączony' }),
  ).not.toBeChecked()

  // 7. Czat/retrieval na pytaniu z state.json: test retrievalu zwraca trafienia z pliku bazy.
  await page.getByRole('button', { name: 'Wstecz' }).click()
  await expect(page).toHaveURL(/\/dataset\/files\//)
  await page.getByRole('tab', { name: 'Test retrievalu' }).click()
  await expect(page).toHaveURL(/\/dataset\/retrieval\//)
  await page.getByLabel('Pytanie').fill(state.question)
  await page.getByRole('button', { name: 'Uruchom' }).click()
  const total = page.getByText(/Łącznie \d+/)
  await expect(total).toBeVisible({ timeout: UI_TIMEOUT_MS })
  const hits = Number((await total.innerText()).replace(/\D/g, ''))
  expect(hits, 'liczba trafień testu retrievalu').toBeGreaterThanOrEqual(1)
  await expect(page.getByText(pdfName, { exact: true }).first()).toBeVisible()
  await expect(
    page.getByText(state.disabledText),
    'wyłączony chunk poza wynikami (okno UI)',
  ).toHaveCount(0)

  // 8. Asercja precyzyjna przez API (pełna treść, bez okna podświetlenia — wzór mcp-prod.spec.ts):
  //    pytanie zwraca cytat z pliku bazy, a wyłączony chunk nie ma jej w wynikach.
  const login = await request.post('/api/v1/auth/login', {
    data: { email: ADMIN_EMAIL, password: ADMIN_PASSWORD },
  })
  expect(login.status(), 'POST /api/v1/auth/login').toBe(200)
  const authorization = login.headers()['authorization']
  expect(authorization, 'nagłówek Authorization po logowaniu').toBeTruthy()
  const searchResponse = await request.post('/api/v1/retrieval', {
    headers: { authorization: authorization! },
    data: { question: state.question, dataset_ids: [datasetId] },
  })
  expect(searchResponse.status(), 'POST /api/v1/retrieval').toBe(200)
  const result = (await searchResponse.json()) as {
    code: number
    data: { chunks: { content: string; document_keyword: string }[] }
  }
  expect(result.code, 'koperta retrievalu').toBe(0)
  expect(result.data.chunks.length, 'trafienia retrievalu przez API').toBeGreaterThan(0)
  expect(
    result.data.chunks.some((chunk) => chunk.content.includes(state.question)),
    'pytanie zwraca cytat z treści pliku bazy',
  ).toBe(true)
  expect(
    result.data.chunks.some((chunk) => chunk.document_keyword === pdfName),
    'źródło cytatu = plik bazy',
  ).toBe(true)
  expect(
    result.data.chunks.every((chunk) => !chunk.content.includes(state.disabledText)),
    'wyłączony chunk nie jest w wynikach retrievalu',
  ).toBe(true)
})
