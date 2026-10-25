// Scenariusz S16 (kontrakt WP E5-H6a §C1, usterki U4/p. 2/U3): dwa uploady po jednym pliku
// w dialogu „Prześlij pliki” datasetu. Pierwszy plik wybieramy ukrytym inputem, drugi prawdziwym
// drag & drop (`DataTransfer`, helper z S15, `setInputFiles` tam zabronione). Kluczowe jest to,
// że po „Zamknij” i ponownym otwarciu kolejka dialogu jest PUSTA — inaczej drugi upload wysłałby
// też pierwszy plik i na liście byłyby 3 dokumenty. Nagłówek zbioru („N plików · rozmiar”) musi
// się zgodzić z listą (U3), co wymaga unieważnienia zapytania szczegółu zbioru po uploadzie.
// Backend nie jest mockowany — asercje patrzą na realny stan listy i nagłówka.
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

import type { APIRequestContext, Page } from '@playwright/test'

import { expect, resetDb, test } from './fixtures'
import { apiLogin, createDataset, loginViaUi } from './helpers'
import { dropFile } from './helpers/dnd'
import { deleteAllFiles, deleteDataset } from './helpers/files'

const DATASET_NAME = 'E2E S16 kolejka uploadu'
const FIRST_FILE = 'sample.pdf'
const SECOND_FILE = 'sample.docx'
const MIME_DOCX = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
// Upload + odświeżenie listy i nagłówka; parsowanie nie jest przedmiotem scenariusza.
const UPLOAD_TIMEOUT_MS = 60_000

/** Ścieżka próbki z `e2e/fixtures` (chooser) i jej bajty (drag & drop przez most Playwrighta). */
function fixturePath(name: string): string {
  return fileURLToPath(new URL(`./fixtures/${name}`, import.meta.url))
}

function fixtureBytes(name: string): Buffer {
  return readFileSync(fixturePath(name))
}

/**
 * Sprzątanie po KAŻDYM teście, nie `afterAll`: `resetDb` na starcie drugiego testu zakłada nowy
 * tenant, więc token z pierwszego testu traci prawo do jego datasetu (jak w S15).
 */
let cleanup: { token: string; datasetId?: string } | undefined

test.afterEach(async ({ request }) => {
  if (cleanup === undefined) return
  await deleteAllFiles(request, cleanup.token)
  if (cleanup.datasetId !== undefined) {
    await deleteDataset(request, cleanup.token, cleanup.datasetId)
  }
  cleanup = undefined
})

/** Baz wiedzy z API + login przez UI + wejście na zakładkę „Pliki” (wzór: S15). */
async function openDatasetFiles(page: Page, request: APIRequestContext): Promise<void> {
  await resetDb(request)
  const token = await apiLogin(request)
  const datasetId = await createDataset(request, token, DATASET_NAME)
  cleanup = { token, datasetId }

  await loginViaUi(page)
  await page.goto(`/dataset/files/${datasetId}`)
  await expect(page.getByRole('heading', { name: DATASET_NAME })).toBeVisible()
}

/**
 * Dwa uploady po jednym pliku: pierwszy przez input, drugi przez drag & drop — z przerwą na
 * „Zamknij” i ponowne otwarcie (tam sprawdzamy, że dialog startuje pusty).
 */
async function uploadTwoFilesOneByOne(page: Page): Promise<void> {
  // 1. Pierwszy plik i wysyłka.
  await page.getByTestId('files-add').click()
  let dialog = page.getByRole('dialog')
  await expect(dialog).toBeVisible()
  await dialog.getByTestId('upload-input').setInputFiles(fixturePath(FIRST_FILE))
  await expect(dialog.getByText(FIRST_FILE)).toBeVisible()
  await page.getByTestId('upload-start').click()
  await expect(dialog.getByText('Przesłano', { exact: true })).toBeVisible({
    timeout: UPLOAD_TIMEOUT_MS,
  })
  await dialog.getByRole('button', { name: 'Gotowe' }).click()
  await expect(dialog).toBeHidden()

  // 2. Ponowne otwarcie: kolejka MUSI być pusta (usterka U4 — bez czyszczenia zostałby pierwszy plik).
  await page.getByTestId('files-add').click()
  dialog = page.getByRole('dialog')
  await expect(dialog).toBeVisible()
  await expect(dialog.getByText(FIRST_FILE)).toBeHidden()

  await dropFile(
    page,
    dialog.getByTestId('upload-dropzone'),
    fixtureBytes(SECOND_FILE),
    SECOND_FILE,
    MIME_DOCX,
  )
  await expect(dialog.getByText(SECOND_FILE)).toBeVisible()
  await page.getByTestId('upload-start').click()
  await expect(dialog.getByText('Przesłano', { exact: true })).toBeVisible({
    timeout: UPLOAD_TIMEOUT_MS,
  })
  await dialog.getByRole('button', { name: 'Gotowe' }).click()
}

/**
 * Dokładnie dwa dokumenty (nie trzy) i nagłówek zbioru zgodny z listą (pl: „2 pliki”).
 * Wiersze danych rozpoznajemy po linku nazwy — samo `[data-field="name"]` łapie też komórkę
 * nagłówka kolumny (MUI X), co zawyżyłoby liczbę o jeden.
 */
async function expectTwoDocuments(page: Page): Promise<void> {
  const rows = page
    .getByTestId('files-grid')
    .getByRole('row')
    .filter({ has: page.getByRole('link') })
  await expect(rows).toHaveCount(2, { timeout: UPLOAD_TIMEOUT_MS })
  await expect(rows.filter({ has: page.getByRole('link', { name: FIRST_FILE }) })).toHaveCount(1)
  await expect(rows.filter({ has: page.getByRole('link', { name: SECOND_FILE }) })).toHaveCount(1)

  // Licznik plików w nagłówku zbioru (U3) — odmiana pl dla 2 („2 pliki · …”).
  await expect(page.getByText(/^2 pliki · /)).toBeVisible()
}

test('S16 A (desktop): kolejka czyszczona po zamknięciu — 2 dokumenty i licznik w nagłówku', async ({
  page,
  request,
}) => {
  test.setTimeout(180_000)

  await openDatasetFiles(page, request)
  await uploadTwoFilesOneByOne(page)
  await expectTwoDocuments(page)
})

test('S16 B (390×844): ten sam scenariusz na wąskim ekranie', async ({ page, request }) => {
  test.setTimeout(180_000)
  await page.setViewportSize({ width: 390, height: 844 })

  await openDatasetFiles(page, request)
  await uploadTwoFilesOneByOne(page)
  await expectTwoDocuments(page)
})
