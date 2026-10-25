// Scenariusz S6-03 (08 §11.2, kontrakt WP E3-3b §T8): upload trzech próbek (PDF, DOCX, XLSX)
// z włączonym „Parsuj po przesłaniu” i doprowadzenie ich do „Sukces” z chunkiem w każdym.
// Baza powstaje przez API (helper `createDataset`), UI sprawdza dialog przesyłania i siatkę plików.
// Drugi akt S6-03 (stop dużego pliku) jest w `s03b-upload-stop.spec.ts` — limit 300 linii.
import { fileURLToPath } from 'node:url'
import type { Page } from '@playwright/test'

import { expect, resetDb, test } from './fixtures'
import { POLL_TIMEOUT_MS, apiLogin, createDataset, loginViaUi } from './helpers'
import { expectNoSeriousA11y } from './helpers/axe'

const DATASET_NAME = 'E2E S6-03 baza'

/** Próbki zacommitowane w `e2e/fixtures` (pochodzenie: `e2e/README.md`). */
const SAMPLES = ['sample.pdf', 'sample.docx', 'sample.xlsx'] as const

/** Ścieżka bezwzględna próbki — `setInputFiles` nie przyjmuje ścieżek względnych. */
function samplePath(name: string): string {
  return fileURLToPath(new URL(`./fixtures/${name}`, import.meta.url))
}

/** Wiersz siatki dokumentu o danej nazwie (`role=row`; nazwa jest linkiem kolumny „Nazwa"). */
function documentRow(page: Page, name: string) {
  return page.getByRole('row').filter({ has: page.getByRole('link', { name }) })
}

/** Komórka kolumny — `data-field` nadaje komórkom `DataGrid` (MUI X 9). */
const STATUS_CELL = '[data-testid^="status-cell-"]'
const CHUNKS_CELL = '[data-field="chunk_count"]'

test('S6-03: upload 3 plików z parsowaniem — status „Sukces” i chunki > 0', async ({
  page,
  request,
}) => {
  // Pętla odpytywania statusu (POLL_TIMEOUT_MS = 90 s) plus narzut na upload i parsowanie.
  test.setTimeout(240_000)

  await resetDb(request)
  const token = await apiLogin(request)
  const datasetId = await createDataset(request, token, DATASET_NAME)

  await loginViaUi(page)
  await page.goto(`/dataset/files/${datasetId}`)
  await expect(page.getByRole('heading', { name: DATASET_NAME })).toBeVisible()

  // 1. Dialog przesyłania: trzy próbki, „Parsuj po przesłaniu” włączone domyślnie.
  await page.getByTestId('files-add').click()
  const dialog = page.getByRole('dialog')
  await expect(dialog).toBeVisible()
  await page.getByTestId('upload-input').setInputFiles(SAMPLES.map(samplePath))
  await expect(page.getByTestId('upload-parse-toggle')).toBeChecked()
  await page.getByTestId('upload-start').click()

  // 2. Koniec przesyłania: każda próbka „Przesłano”, a przycisk znów aktywny (po żądaniu
  //    parsowania). Zamknięcie dialogu dopiero tutaj — inaczej lista nie zostałaby odświeżona.
  await expect(dialog.getByText('Przesłano', { exact: true })).toHaveCount(SAMPLES.length, {
    timeout: POLL_TIMEOUT_MS,
  })
  await expect(page.getByTestId('upload-start')).toBeDisabled({ timeout: POLL_TIMEOUT_MS }) // po sukcesie T15b
  await dialog.getByRole('button', { name: 'Gotowe' }).click()
  await expect(dialog).toBeHidden()

  // 3. Wiersze pojawiają się i dochodzą do „Sukces”; pasek postępu („Parsowanie” z %) jest po
  //    drodze tylko przejściem — siatka odświeża się co 3 s (`POLL_INTERVAL_MS` T1a), więc
  //    asercja stanu pośredniego byłaby wyścigiem i świadomie jej nie ma.
  for (const name of SAMPLES) {
    const row = documentRow(page, name)
    await expect(row, `wiersz dokumentu ${name}`).toBeVisible({ timeout: POLL_TIMEOUT_MS })
    await expect(row.locator(STATUS_CELL), `status dokumentu ${name}`).toHaveText('Sukces', {
      timeout: POLL_TIMEOUT_MS,
    })
    // `formatNumber` wstawia separator tysięcy (spacja nierozdzielająca) — usuwamy białe znaki.
    const chunks = (await row.locator(CHUNKS_CELL).innerText()).replace(/\s/g, '')
    expect(Number(chunks), `chunki dokumentu ${name}`).toBeGreaterThan(0)
  }

  // Główny ekran scenariusza: siatka plików datasetu po sparsowaniu (jasny motyw).
  await expectNoSeriousA11y(page, 'S6-03 pliki datasetu')

  // 4. Sortowanie po nazwie jest serwerowe (kontrakt WP E3-H2a §K1, DEC-138): klik nagłówka
  //    „Nazwa” wysyła żądanie listy z `orderby=name`. Nasłuch przed kliknięciem, inaczej żądanie
  //    mogłoby umknąć.
  const nameSortRequest = page.waitForRequest((request) => {
    if (request.method() !== 'GET') return false
    const url = new URL(request.url())
    return url.pathname.endsWith('/documents') && url.searchParams.get('orderby') === 'name'
  })
  await page.getByRole('columnheader', { name: /Nazwa/ }).click()
  await nameSortRequest
})
