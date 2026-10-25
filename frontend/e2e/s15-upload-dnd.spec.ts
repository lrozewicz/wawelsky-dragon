// Scenariusz S15 (kontrakt WP E5-H3 §„Plan testów", usterka #5): upload przez przeciągnięcie
// pliku prawdziwym `DataTransfer` w OBU strefach upuszczania — dialogu plików datasetu
// (`upload-dropzone`) oraz menedżera plików (`files-upload-dropzone`). Zdarzenia `dragenter`/
// `dragover`/`drop` lecą na element strefy (helper `dropFile`), a bajty pliku powstają z
// `fixtures/sample.pdf`; `setInputFiles` jest zabronione, bo ominęłoby ścieżkę `drop`.
// Backend nie jest mockowany — asercje patrzą na realny POST uploadu i stan pozycji listy.
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

import { expect, resetDb, test } from './fixtures'
import { apiLogin, createDataset, loginViaUi } from './helpers'
import { dropFile } from './helpers/dnd'
import { deleteAllFiles, deleteDataset } from './helpers/files'

const DATASET_NAME = 'E2E S15 baza dnd'
const FILE_NAME = 'sample.pdf'
const MIME = 'application/pdf'

/** Bajty próbki z `e2e/fixtures` — ten sam plik czyta Node i wstrzykuje do `File` na stronie. */
function sampleBytes(): Buffer {
  return readFileSync(fileURLToPath(new URL(`./fixtures/${FILE_NAME}`, import.meta.url)))
}

/**
 * Sprzątanie po KAŻDYM teście, nie `afterAll`: `resetDb` na starcie drugiego testu zakłada nowy
 * tenant, więc token z pierwszego testu traci prawo do jego datasetu (błąd 102 na DELETE).
 * `afterEach` biegnie jeszcze w tenancie, w którym zasoby powstały.
 */
let cleanup: { token: string; datasetId?: string } | undefined

test.afterEach(async ({ request }) => {
  if (cleanup === undefined) return
  // Menedżer plików jest wspólny dla całego stosu — czyścimy go w obu przypadkach.
  await deleteAllFiles(request, cleanup.token)
  if (cleanup.datasetId !== undefined) {
    await deleteDataset(request, cleanup.token, cleanup.datasetId)
  }
  cleanup = undefined
})

test('S15 A: drop do strefy dialogu datasetu — POST uploadu i plik na liście', async ({
  page,
  request,
}) => {
  test.setTimeout(120_000)

  await resetDb(request)
  const token = await apiLogin(request)
  const datasetId = await createDataset(request, token, DATASET_NAME)
  cleanup = { token, datasetId }

  await loginViaUi(page)
  await page.goto(`/dataset/files/${datasetId}`)
  await expect(page.getByRole('heading', { name: DATASET_NAME })).toBeVisible()

  // „Prześlij plik” otwiera dialog; dropzone jest w dialogu.
  await page.getByTestId('files-add').click()
  const dialog = page.getByRole('dialog')
  await expect(dialog).toBeVisible()

  // Nasłuch PRZED klikiem „Prześlij”, inaczej żądanie mogłoby umknąć (upload startuje dopiero
  // przyciskiem, ale rejestracja wcześniej jest jednoznaczna).
  const uploadRequest = page.waitForRequest((candidate) => {
    if (candidate.method() !== 'POST') return false
    return new URL(candidate.url()).pathname.endsWith('/documents')
  })

  await dropFile(page, page.getByTestId('upload-dropzone'), sampleBytes(), FILE_NAME, MIME)
  // Nazwa pliku na liście dialogu — dowód, że `File` z `DataTransfer` dotarł do stanu komponentu.
  await expect(dialog.getByText(FILE_NAME)).toBeVisible()

  await page.getByTestId('upload-start').click()

  const posted = await uploadRequest
  const postedUrl = new URL(posted.url())
  expect(postedUrl.pathname, 'ścieżka POST uploadu').toBe(`/api/v1/datasets/${datasetId}/documents`)
  // Usterka #5 objawiała się „Błąd przesyłania” — pozycja musi dojść do „Przesłano”, nie do błędu.
  await expect(dialog.getByText('Przesłano', { exact: true })).toBeVisible({ timeout: 60_000 })
  await expect(dialog.getByText('Błąd przesyłania')).toBeHidden()
})

test('S15 B: drop do strefy menedżera plików — POST uploadu i pozycja „Przesłano”', async ({
  page,
  request,
}) => {
  test.setTimeout(120_000)

  await resetDb(request)
  const token = await apiLogin(request)
  cleanup = { token }

  await loginViaUi(page)
  await page.goto('/files')
  await expect(page.getByRole('heading', { name: 'Pliki' })).toBeVisible()

  // Menu „Prześlij plik” → dialog menedżera ze strefą `files-upload-dropzone`.
  await page.getByTestId('files-add').click()
  await page.getByTestId('files-add-upload').click()
  const dialog = page.getByRole('dialog')
  await expect(dialog).toBeVisible()

  const uploadRequest = page.waitForRequest((candidate) => {
    if (candidate.method() !== 'POST') return false
    return new URL(candidate.url()).pathname.endsWith('/api/v1/files')
  })

  // W menedżerze drop startuje wysyłanie od razu (bez osobnego „Prześlij”).
  await dropFile(page, page.getByTestId('files-upload-dropzone'), sampleBytes(), FILE_NAME, MIME)

  const item = dialog.getByTestId('files-upload-item-0')
  await expect(item).toBeVisible()
  await expect(item).toContainText(FILE_NAME)
  await expect(item.getByText('Przesłano')).toBeVisible({ timeout: 60_000 })
  await uploadRequest

  await page.getByTestId('files-upload-close').click()
  await expect(dialog).toBeHidden()
})
