// Scenariusz SC-V12-09 (kroki 3–4) z work/wp/V12/SCENARIOS.md, brief V12-2 T6: podgląd pliku
// bez obsługi (.xlsx) — komunikat „Podgląd niedostępny dla tego typu pliku” + działające
// „Pobierz” zamiast pustego prostokąta (DEC-357), oraz podpowiedź przy „Tylko nowe pliki”
// w dialogu „Zastosować zmiany do istniejących plików?” (klucz datasets.config.apply.newOnlyHint).
// Kroki 1–2 (log parsowania) testuje s28-v12-messages.spec.ts (T3b) — ten plik ich nie dotyka.
// Wzorce: s28-v12-messages.spec.ts (sesja, zrzuty), s25-metadata-config.spec.ts (metadane, dialog).
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

import type { APIRequestContext, APIResponse, Locator, Page } from '@playwright/test'

import { expect, test } from './fixtures'
import { apiLogin, createDataset, seedCorpus } from './helpers'
import type { SeededCorpus } from './helpers'
import { deleteDataset } from './helpers/files'
import { expectNoLayoutDefects } from './helpers/layout'
import { setProfileLanguage } from './helpers/models'
import { uiSession } from './helpers/session'

const SHOTS = process.env.WD_SHOTS_DIR ?? ''
const API_URL = process.env.WD_E2E_API_URL ?? ''

const XLSX_NAME = 'podglad-e2e.xlsx'
const XLSX_PATH = fileURLToPath(new URL('./fixtures/sample.xlsx', import.meta.url))
const XLSX_MIME = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'

const PREVIEW_UNAVAILABLE = 'Podgląd niedostępny dla tego typu pliku'
const PREVIEW_UNAVAILABLE_EN = 'Preview not available for this file type.'
const NEW_ONLY_HINT =
  'Istniejące pliki zachowają dotychczasowe metadane. Aby je dodać, użyj „Zastosuj i parsuj ponownie”.'
const NEW_ONLY_HINT_EN =
  'Existing files keep their current metadata. To add it, use "Apply and re-parse".'
const APPLY_TITLE = 'Zastosować zmiany do istniejących plików?'

const META_DATASET = `E2E V12-2 T6 metadane ${Date.now()}`

const session = uiSession('s28-v12-parselog')
test.use({ storageState: session.statePath, colorScheme: 'light' })
test.setTimeout(240_000)

let token = ''
let previewDatasetId = ''
let metaCorpus: SeededCorpus

test.beforeAll(async ({ browser }) => {
  await session.login(browser)
})

test.beforeAll(async ({ request }) => {
  token = await apiLogin(request)
  previewDatasetId = await createDataset(request, token, 'E2E V12-2 T6 podgląd')
  // Podgląd otwierany klikami użytkownika z listy plików — id dokumentu nie jest potrzebny.
  await uploadXlsx(request, token, previewDatasetId)
  metaCorpus = await seedCorpus(request, token, {
    datasetName: META_DATASET,
    documentName: 'e2e-t6-notatka.txt',
    documentBody: 'Notatka do SC-V12-09 krok 4 — zmiana metadanych i podpowiedź.',
  })
})

test.afterAll(async ({ request }) => {
  await deleteDataset(request, token, previewDatasetId)
  await deleteDataset(request, token, metaCorpus.datasetId)
})

test.afterEach(async ({ context }) => {
  await session.save(context)
})

type Envelope<T> = { code: number; message: string; data: T }

/** Rozwija kopertę RAGFlow (wzór: s25-metadata-config). */
async function ok<T>(pending: Promise<APIResponse>, label: string): Promise<T> {
  const response = await pending
  const body = (await response.json()) as Envelope<T>
  expect(response.status(), `${label}: HTTP ${response.status()} — ${body.message}`).toBe(200)
  expect(body.code, `${label}: ${body.message}`).toBe(0)
  return body.data
}

/** Wgrywa próbkę .xlsx przez API (multipart, wzór: s25) i zwraca id dokumentu. */
async function uploadXlsx(
  request: APIRequestContext,
  bearer: string,
  datasetId: string,
): Promise<string> {
  const uploaded = await ok<{ id: string }[]>(
    request.post(`${API_URL}/api/v1/datasets/${datasetId}/documents`, {
      headers: { authorization: `Bearer ${bearer}` },
      multipart: {
        file: {
          name: XLSX_NAME,
          mimeType: XLSX_MIME,
          buffer: readFileSync(XLSX_PATH),
        },
      },
    }),
    `POST /api/v1/datasets/{id}/documents (${XLSX_NAME})`,
  )
  expect(uploaded, 'upload xlsx: dokładnie jeden dokument').toHaveLength(1)
  return uploaded[0]!.id
}

/** Panel podglądu lewej strony ChunksPage (nagłówek „Podgląd dokumentu”). */
function previewPane(page: Page): Locator {
  return page.getByTestId('chunks-preview')
}

/** Otwiera podgląd .xlsx krokami użytkownika: lista plików → klik w nazwę dokumentu. */
async function openXlsxPreview(page: Page, heading = 'Podgląd dokumentu'): Promise<void> {
  await page.goto(`/dataset/files/${previewDatasetId}`)
  await page.getByRole('link', { name: XLSX_NAME }).click()
  const pane = previewPane(page)
  await expect(pane.getByRole('heading', { name: heading })).toBeVisible()
  await expect(page.getByTestId('chunks-page')).toBeVisible()
}

async function shot(page: Page, name: string): Promise<void> {
  if (SHOTS !== '') await page.screenshot({ path: `${SHOTS}/${name}.png` })
}

test('SC-V12-09 k3 UI PL: podgląd .xlsx — komunikat i „Pobierz”, nie pusty prostokąt', async ({
  page,
}) => {
  await page.setViewportSize({ width: 1280, height: 800 })
  await openXlsxPreview(page)
  const pane = previewPane(page)
  await expect(pane.getByText(PREVIEW_UNAVAILABLE)).toBeVisible()
  await expect(pane.getByRole('link', { name: 'Pobierz' })).toBeVisible()
  // „Nie pusty prostokąt”: podgląd nie renderuje ramki PDF/HTML ani pustej treści.
  await expect(pane.locator('iframe')).toHaveCount(0)
  await shot(page, 'sc09-preview-pl-1280')
  await shot(page, 'desktop')
  await expectNoLayoutDefects(page, 'SC-V12-09 k3: podgląd .xlsx z komunikatem (PL, 1280)')
})

test('SC-V12-09 k3 UI PL: „Pobierz” z podglądu zwraca oryginalny plik', async ({ page }) => {
  await openXlsxPreview(page)
  const link = previewPane(page).getByRole('link', { name: 'Pobierz' })
  await expect(link).toBeVisible()
  const [download] = await Promise.all([page.waitForEvent('download'), link.click()])
  expect(download.suggestedFilename()).toBe(XLSX_NAME)
  const path = await download.path()
  expect(readFileSync(path).equals(readFileSync(XLSX_PATH)), 'treść pobranego pliku').toBe(true)
})

test('SC-V12-09 k3 UI PL 390: komunikat podglądu mieści się w panelu', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await openXlsxPreview(page)
  const pane = previewPane(page)
  await expect(pane.getByText(PREVIEW_UNAVAILABLE)).toBeVisible()
  await expect(pane.getByRole('link', { name: 'Pobierz' })).toBeVisible()
  await shot(page, 'sc09-preview-pl-390')
  await shot(page, 'mobile')
  await expectNoLayoutDefects(page, 'SC-V12-09 k3: podgląd .xlsx (PL, 390)')
})

test('SC-V12-09 k3 UI PL (ciemny): komunikat podglądu czytelny w ciemnym motywie', async ({
  page,
}) => {
  await page.emulateMedia({ colorScheme: 'dark' })
  await page.setViewportSize({ width: 1280, height: 800 })
  await openXlsxPreview(page)
  await expect(previewPane(page).getByText(PREVIEW_UNAVAILABLE)).toBeVisible()
  await shot(page, 'sc09-preview-pl-dark-1280')
  await expectNoLayoutDefects(page, 'SC-V12-09 k3: podgląd .xlsx (PL, ciemny)')
})

test('SC-V12-09 k3 UI EN: podgląd .xlsx — „Preview not available…” i „Download”', async ({
  page,
  request,
}) => {
  await page.setViewportSize({ width: 1280, height: 800 })
  await setProfileLanguage(request, token, 'en')
  try {
    await openXlsxPreview(page, 'Document preview')
    const pane = previewPane(page)
    await expect(pane.getByText(PREVIEW_UNAVAILABLE_EN)).toBeVisible()
    await expect(pane.getByRole('link', { name: 'Download' })).toBeVisible()
    await shot(page, 'sc09-preview-en-1280')
  } finally {
    await setProfileLanguage(request, token, 'pl')
  }
})

test('SC-V12-09 k3 (regresja): pusta odpowiedź podglądu — komunikat zamiast pustego panelu', async ({
  page,
}) => {
  // Backend (awaria, pusty plik) może zwrócić 200 bez treści — pusty blob rozmiaru 0 ma dać
  // komunikat jak dla typu nieobsługiwanego (DEC-357), nie pusty <pre>/ramkę.
  await page.route('**/api/v1/documents/*/preview', (route) =>
    route.fulfill({ status: 200, headers: { 'Content-Type': 'application/pdf' }, body: '' }),
  )
  await openXlsxPreview(page)
  await expect(previewPane(page).getByText(PREVIEW_UNAVAILABLE)).toBeVisible()
})

/**
 * Zakładka „Konfiguracja”: dodaje pole metadanych (OSTATNI wiersz — testy nie mogą zależeć od
 * kolejności, bo `-g` uruchamia każdy w osobnym stosie), zapisuje i czeka na dialog zastosowania.
 */
async function addFieldAndSave(
  page: Page,
  opts: { add: string; group: RegExp; keyLabel: string; key: string; save: string; title?: string },
): Promise<Locator> {
  await page.getByRole('button', { name: opts.add }).click()
  const row = page.getByRole('group', { name: opts.group }).last()
  await expect(row).toBeVisible()
  await row.getByLabel(opts.keyLabel).fill(opts.key)
  await page.getByRole('button', { name: opts.save }).click()
  const dialog = page.getByRole('dialog', { name: opts.title ?? APPLY_TITLE })
  await expect(dialog).toBeVisible()
  // Zrzut/asercje dopiero po domknięciu animacji MUI (wzór: s07 — w trakcie Fade zrzut łapie
  // półprzezroczysty dialog).
  await expect(page.locator('.MuiDialog-container')).toHaveCSS('opacity', '1')
  return dialog
}

const PL_FIELD = { add: '+ Pole', group: /Pole \d/, keyLabel: 'Klucz', save: 'Zapisz' }

test('SC-V12-09 k4 UI PL: zmiana metadanych — podpowiedź obok „Tylko nowe pliki”', async ({
  page,
}) => {
  await page.setViewportSize({ width: 1280, height: 800 })
  await page.goto(`/dataset/configuration/${metaCorpus.datasetId}`)
  await expect(page.getByRole('heading', { name: META_DATASET })).toBeVisible()

  const dialog = await addFieldAndSave(page, { ...PL_FIELD, key: `rok-${Date.now()}` })
  const hint = dialog.getByText(NEW_ONLY_HINT)
  await expect(hint).toBeVisible()
  // „Obok przycisku”: podpowiedź leży w strefie akcji dialogu, przed „Tylko nowe pliki”.
  await expect
    .poll(() => hint.evaluate((el) => el.closest('.MuiDialogActions-root') !== null))
    .toBe(true)
  const newOnly = dialog.getByRole('button', { name: 'Tylko nowe pliki' })
  await expect(newOnly).toBeVisible()
  await shot(page, 'sc09-newonly-pl-1280')
  await expectNoLayoutDefects(page, 'SC-V12-09 k4: dialog z podpowiedzią (PL, 1280)')

  // Krok użytkownika ze scenariusza: „Tylko nowe pliki” zamyka dialog (zapis już się dokonał).
  await newOnly.click()
  await expect(dialog).toBeHidden()
})

test('SC-V12-09 k4 UI PL 390: podpowiedź mieści się w dialogu', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto(`/dataset/configuration/${metaCorpus.datasetId}`)
  await expect(page.getByRole('heading', { name: META_DATASET })).toBeVisible()

  const dialog = await addFieldAndSave(page, { ...PL_FIELD, key: `typ-${Date.now()}` })
  await expect(dialog.getByText(NEW_ONLY_HINT)).toBeVisible()
  await shot(page, 'sc09-newonly-pl-390')
  await expectNoLayoutDefects(page, 'SC-V12-09 k4: dialog z podpowiedzią (PL, 390)')
  await dialog.getByRole('button', { name: 'Tylko nowe pliki' }).click()
  await expect(dialog).toBeHidden()
})

test('SC-V12-09 k4 UI PL (ciemny): podpowiedź czytelna w ciemnym motywie', async ({ page }) => {
  await page.emulateMedia({ colorScheme: 'dark' })
  await page.setViewportSize({ width: 1280, height: 800 })
  await page.goto(`/dataset/configuration/${metaCorpus.datasetId}`)
  await expect(page.getByRole('heading', { name: META_DATASET })).toBeVisible()

  const dialog = await addFieldAndSave(page, { ...PL_FIELD, key: `autor-${Date.now()}` })
  await expect(dialog.getByText(NEW_ONLY_HINT)).toBeVisible()
  await shot(page, 'sc09-newonly-pl-dark-1280')
  await expectNoLayoutDefects(page, 'SC-V12-09 k4: dialog z podpowiedzią (PL, ciemny)')
  await dialog.getByRole('button', { name: 'Tylko nowe pliki' }).click()
  await expect(dialog).toBeHidden()
})

test('SC-V12-09 k4 UI EN: podpowiedź — „Existing files keep…” i „Apply and re-parse”', async ({
  page,
  request,
}) => {
  await page.setViewportSize({ width: 1280, height: 800 })
  await setProfileLanguage(request, token, 'en')
  try {
    await page.goto(`/dataset/configuration/${metaCorpus.datasetId}`)
    await expect(page.getByRole('heading', { name: META_DATASET })).toBeVisible()

    // Etykiety EN (locales/en/datasets.json): „+ Field”, grupa „Field N”, przycisk „Save”,
    // tytuł dialogu „Apply changes to existing files?”.
    const dialog = await addFieldAndSave(page, {
      add: '+ Field',
      group: /Field \d/,
      keyLabel: 'Key',
      key: `tag-${Date.now()}`,
      save: 'Save',
      title: 'Apply changes to existing files?',
    })
    await expect(dialog.getByText(NEW_ONLY_HINT_EN)).toBeVisible()
    await shot(page, 'sc09-newonly-en-1280')
    await dialog.getByRole('button', { name: 'New files only' }).click()
    await expect(dialog).toBeHidden()
  } finally {
    await setProfileLanguage(request, token, 'pl')
  }
})
