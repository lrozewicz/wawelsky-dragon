// Scenariusz SC-E5-H8d-01 (work/wp/E5-H8d/SCENARIOS.md, R-ING-03): plik 0 B upuszczony do strefy
// (Chrome z Flatpaka nie daje odczytu przeciąganych plików) NIE trafia do kolejki — strefa pokazuje
// ostrzeżenie `upload-unreadable` z pełnym tekstem kontraktu (C2/C3), a pozostałe pliki z tego samego
// upuszczenia wchodzą normalnie i przechodzą upload z parsowaniem do „Sukces”. Prawdziwy `DataTransfer`
// (helpers/dnd.ts); backend nie jest mockowany. Warianty: wybór przez „Wybierz pliki” (krok 3),
// menedżer plików (krok 4), ponowne otwarcie dialogu — ostrzeżenie i kolejka puste (U7) oraz EN.
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

import { expect, resetDb, test } from './fixtures'
import type { Locator, Page } from '@playwright/test'

import { POLL_TIMEOUT_MS, apiLogin, createDataset, loginViaUi } from './helpers'
import { dropFile } from './helpers/dnd'
import { deleteAllFiles, deleteDataset } from './helpers/files'

const DATASET_NAME = 'E2E S18 baza'
const EMPTY_NAME = 'raport.pdf'
// Drugi plik 0 B — do sprawdzenia, że drop po dropie PODMIENIA nazwę w jednym ostrzeżeniu.
const SECOND_EMPTY_NAME = 'notatka.pdf'
const SAMPLE_NAME = 'sample.pdf'
const MIME_PDF = 'application/pdf'

// Teksty ostrzeżenia dla dropu — dosłownie z kontraktu E5-H8d §C2 (interpolacja {{names}}).
const PL_DROP_WARNING =
  'Nie można odczytać pliku »raport.pdf« (0 B). Przeglądarka nie ma dostępu do tego katalogu — ' +
  'użyj »Wybierz pliki« albo nadaj przeglądarce dostęp do katalogu (np. Flatpak: uprawnienie do plików).'
const EN_DROP_WARNING =
  'Cannot read file »raport.pdf« (0 B). The browser has no access to this folder — use »Choose files« ' +
  'or grant the browser access to the folder (e.g. Flatpak: file permission).'
// Tekst EN dla wyboru przez „Choose files” — dosłownie z kontraktu (`common.upload.unreadable.pick`).
const EN_PICK_WARNING = 'The file is empty (0 B): »raport.pdf«.'

/** Bajty próbki z `e2e/fixtures` — ten sam plik czyta Node i wstrzykuje do `File` na stronie (wzór S15). */
function sampleBytes(): Buffer {
  return readFileSync(fileURLToPath(new URL(`./fixtures/${SAMPLE_NAME}`, import.meta.url)))
}

/** Ścieżka bezwzględna próbki — `chooser.setFiles` nie przyjmuje ścieżek względnych (wzór S6-03). */
function samplePath(): string {
  return fileURLToPath(new URL(`./fixtures/${SAMPLE_NAME}`, import.meta.url))
}

/**
 * Upuszcza KILKA plików naraz jednym `DataTransfer` (SC-01 krok 2: „przeciąga naraz”). Sekwencja
 * zdarzeń jak w `helpers/dnd.ts`; osobny helper, bo `dropFile` niesie dokładnie jeden plik.
 */
async function dropFilesAtOnce(
  page: Page,
  locator: Locator,
  files: { bytes: Buffer; name: string; mime: string }[],
): Promise<void> {
  const dataTransfer = await page.evaluateHandle(
    (inits: { data: number[]; name: string; mime: string }[]) => {
      const transfer = new DataTransfer()
      for (const init of inits) {
        transfer.items.add(new File([new Uint8Array(init.data)], init.name, { type: init.mime }))
      }
      return transfer
    },
    files.map((file) => ({ data: [...file.bytes], name: file.name, mime: file.mime })),
  )
  await locator.dispatchEvent('dragenter', { dataTransfer })
  await locator.dispatchEvent('dragover', { dataTransfer })
  await locator.dispatchEvent('drop', { dataTransfer })
}

/** Upuszcza plik 0 B (kontrakt C4: bajty puste przez `Buffer.alloc(0)`). */
async function dropEmptyFile(
  page: Page,
  locator: Locator,
  name: string = EMPTY_NAME,
): Promise<void> {
  await dropFile(page, locator, Buffer.alloc(0), name, MIME_PDF)
}

/**
 * Sprzątanie po KAŻDYM teście (wzór S15): `resetDb` na starcie kolejnego testu zakłada nowy tenant,
 * więc token musiałby tracić prawo do zasobów; `afterEach` biegnie jeszcze w tenancie testu.
 */
let cleanup: { token: string; datasetId?: string } | undefined

test.afterEach(async ({ request }) => {
  if (cleanup === undefined) return
  // Menedżer plików jest wspólny dla całego stosu — czyścimy go zawsze (wzór S15).
  await deleteAllFiles(request, cleanup.token)
  if (cleanup.datasetId !== undefined) {
    await deleteDataset(request, cleanup.token, cleanup.datasetId)
  }
  cleanup = undefined
})

test('SC-E5-H8d-01: drop 0 B daje ostrzeżenie i pustą kolejkę; drop dwóch naraz — tylko sample.pdf (dataset)', async ({
  page,
  request,
}) => {
  // Upload + oczekiwanie na chip „Sukces” (worker) — zapas ponad domyślne 30 s (wzór S6-03).
  test.setTimeout(240_000)

  await resetDb(request)
  const token = await apiLogin(request)
  const datasetId = await createDataset(request, token, DATASET_NAME)
  cleanup = { token, datasetId }

  await loginViaUi(page)
  await page.goto(`/dataset/files/${datasetId}`)
  await expect(page.getByRole('heading', { name: DATASET_NAME })).toBeVisible()

  // Krok 1: drop pliku 0 B do strefy dialogu datasetu.
  await page.getByTestId('files-add').click()
  const dialog = page.getByRole('dialog')
  await expect(dialog).toBeVisible()
  await dropEmptyFile(page, dialog.getByTestId('upload-dropzone'))

  // Ostrzeżenie w strefie z pełnym tekstem kontraktu C2…
  const warning = dialog.getByTestId('upload-unreadable')
  await expect(warning).toBeVisible()
  await expect(warning).toContainText(PL_DROP_WARNING)
  // …a plik NIE trafia do kolejki: lista pusta to wyłączony „Prześlij”.
  await expect(page.getByTestId('upload-start')).toBeDisabled()

  // Krok 1b: drop KOLEJNEGO pliku 0 B — stan `unreadable` jest pojedynczy: nazwa w alercie
  // podmienia się na nową, alert nadal jest dokładnie JEDEN (bez dubli).
  await dropEmptyFile(page, dialog.getByTestId('upload-dropzone'), SECOND_EMPTY_NAME)
  await expect(warning).toContainText(SECOND_EMPTY_NAME)
  await expect(dialog.getByTestId('upload-unreadable')).toHaveCount(1)
  await expect(page.getByTestId('upload-start')).toBeDisabled()

  // Krok 2: drop `raport.pdf` (0 B) i `sample.pdf` NARAZ — ostrzeżenie wymienia `raport.pdf`,
  // kolejka dostaje wyłącznie `sample.pdf` (jeden pasek postępu: indeks 1 nie istnieje).
  await dropFilesAtOnce(page, dialog.getByTestId('upload-dropzone'), [
    { bytes: Buffer.alloc(0), name: EMPTY_NAME, mime: MIME_PDF },
    { bytes: sampleBytes(), name: SAMPLE_NAME, mime: MIME_PDF },
  ])
  await expect(warning).toContainText(EMPTY_NAME)
  await expect(dialog.getByText(SAMPLE_NAME)).toBeVisible()
  await expect(dialog.getByTestId('upload-progress-1')).toHaveCount(0)

  // „Prześlij” i parsowanie `sample.pdf` dochodzą do „Sukces” (chip w wierszu listy, wzór S6-03).
  await page.getByTestId('upload-start').click()
  await expect(dialog.getByText('Przesłano', { exact: true })).toBeVisible({
    timeout: POLL_TIMEOUT_MS,
  })
  await expect(page.getByTestId('upload-start')).toBeDisabled({ timeout: POLL_TIMEOUT_MS }) // po sukcesie T15b
  await dialog.getByRole('button', { name: 'Gotowe' }).click()
  await expect(dialog).toBeHidden()

  const sampleRow = page
    .getByRole('row')
    .filter({ has: page.getByRole('link', { name: SAMPLE_NAME }) })
  await expect(sampleRow, 'wiersz dokumentu sample.pdf').toBeVisible({ timeout: POLL_TIMEOUT_MS })
  await expect(sampleRow.locator('[data-testid^="status-cell-"]')).toHaveText('Sukces', {
    timeout: POLL_TIMEOUT_MS,
  })
  // Plik 0 B nie wszedł na listę datasetu — wiersza `raport.pdf` nie ma.
  await expect(page.getByRole('row').filter({ hasText: EMPTY_NAME })).toHaveCount(0)
})

test('SC-E5-H8d-01: „Wybierz pliki” gasi ostrzeżenie; ponowne otwarcie dialogu — pusto (U7)', async ({
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

  // Stan wyjściowy kroku 3: ostrzeżenie po dropie pliku 0 B.
  await page.getByTestId('files-add').click()
  const dialog = page.getByRole('dialog')
  await expect(dialog).toBeVisible()
  await dropEmptyFile(page, dialog.getByTestId('upload-dropzone'))
  const warning = dialog.getByTestId('upload-unreadable')
  await expect(warning).toBeVisible()

  // Krok 3: klik „Wybierz pliki” i wybór `sample.pdf` (prawdziwy filechooser, jak u użytkownika).
  const chooserPromise = page.waitForEvent('filechooser')
  await dialog.getByRole('button', { name: 'Wybierz pliki' }).click()
  const chooser = await chooserPromise
  await chooser.setFiles(samplePath())

  // Ostrzeżenie znika, plik jest w kolejce (pasek postępu pozycji 0).
  await expect(warning).toBeHidden()
  await expect(dialog.getByTestId('upload-progress-0')).toBeVisible()
  await expect(dialog.getByText(SAMPLE_NAME)).toBeVisible()
  await expect(page.getByTestId('upload-start')).toBeEnabled()

  // Wariant U7: zamknięcie i ponowne otwarcie dialogu — ostrzeżenie ani kolejka nie przeciekają.
  await dialog.getByRole('button', { name: 'Anuluj' }).click()
  await expect(dialog).toBeHidden()
  await page.getByTestId('files-add').click()
  const reopened = page.getByRole('dialog')
  await expect(reopened).toBeVisible()
  await expect(reopened.getByTestId('upload-unreadable')).toHaveCount(0)
  await expect(page.getByTestId('upload-start')).toBeDisabled()
})

test('SC-E5-H8d-01: menedżer plików — identyczne zachowanie i tekst (Pliki → Prześlij)', async ({
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

  await page.getByTestId('files-add').click()
  await page.getByTestId('files-add-upload').click()
  const dialog = page.getByRole('dialog')
  await expect(dialog).toBeVisible()

  // Krok 1 w menedżerze: drop pliku 0 B — ostrzeżenie z TYM SAMYM tekstem, kolejka pusta
  // (w menedżerze drop startuje wysyłkę, więc pozycja `files-upload-item-0` nie może powstać).
  await dropEmptyFile(page, dialog.getByTestId('files-upload-dropzone'))
  const warning = dialog.getByTestId('upload-unreadable')
  await expect(warning).toBeVisible()
  await expect(warning).toContainText(PL_DROP_WARNING)
  await expect(dialog.getByTestId('files-upload-item-0')).toHaveCount(0)

  // Drop dwóch naraz: w kolejce wyłącznie `sample.pdf`, ostrzeżenie wymienia `raport.pdf`,
  // a automatyczna wysyłka kończy się „Przesłano”.
  await dropFilesAtOnce(page, dialog.getByTestId('files-upload-dropzone'), [
    { bytes: Buffer.alloc(0), name: EMPTY_NAME, mime: MIME_PDF },
    { bytes: sampleBytes(), name: SAMPLE_NAME, mime: MIME_PDF },
  ])
  await expect(warning).toContainText(EMPTY_NAME)
  const item = dialog.getByTestId('files-upload-item-0')
  await expect(item).toBeVisible()
  await expect(item).toContainText(SAMPLE_NAME)
  await expect(dialog.getByTestId('files-upload-item-1')).toHaveCount(0)
  await expect(item.getByText('Przesłano')).toBeVisible({ timeout: POLL_TIMEOUT_MS })

  // Wariant U7 w menedżerze: kolejny dialog startuje bez ostrzeżenia i bez kolejki.
  await page.getByTestId('files-upload-close').click()
  await expect(dialog).toBeHidden()
  await page.getByTestId('files-add').click()
  await page.getByTestId('files-add-upload').click()
  const reopened = page.getByRole('dialog')
  await expect(reopened).toBeVisible()
  await expect(reopened.getByTestId('upload-unreadable')).toHaveCount(0)
  await expect(reopened.getByTestId('files-upload-item-0')).toHaveCount(0)
})

test('SC-E5-H8d-01: ostrzeżenie o nieczytelnym pliku po angielsku (EN)', async ({
  page,
  request,
}) => {
  test.setTimeout(120_000)

  await resetDb(request)
  const token = await apiLogin(request)
  const datasetId = await createDataset(request, token, DATASET_NAME)
  cleanup = { token, datasetId }

  await loginViaUi(page)
  // Zmiana języka na EN nagłówkiem (wzór S6-10): „Język” → „English”.
  await page.getByRole('button', { name: 'Język' }).click()
  await page.getByRole('menuitem', { name: 'English' }).click()
  await expect(page.getByRole('navigation').getByRole('link', { name: 'Datasets' })).toBeVisible()

  await page.goto(`/dataset/files/${datasetId}`)
  await expect(page.getByRole('heading', { name: DATASET_NAME })).toBeVisible()
  await page.getByTestId('files-add').click()
  const dialog = page.getByRole('dialog')
  await expect(dialog).toBeVisible()
  await dropEmptyFile(page, dialog.getByTestId('upload-dropzone'))

  // Tekst EN dosłownie z kontraktu C2 (`upload.unreadable.drop`).
  const warning = dialog.getByTestId('upload-unreadable')
  await expect(warning).toBeVisible()
  await expect(warning).toContainText(EN_DROP_WARNING)
  await expect(page.getByTestId('upload-start')).toBeDisabled()

  // Wybór pliku 0 B przez „Choose files” — inny klucz komunikatu (`common.upload.unreadable.pick`).
  const chooserPromise = page.waitForEvent('filechooser')
  await dialog.getByRole('button', { name: 'Choose files' }).click()
  await (
    await chooserPromise
  ).setFiles({
    name: EMPTY_NAME,
    mimeType: MIME_PDF,
    buffer: Buffer.alloc(0),
  })
  await expect(warning).toContainText(EN_PICK_WARNING)
  await expect(dialog.getByTestId('upload-unreadable')).toHaveCount(1)
  await expect(page.getByTestId('upload-start')).toBeDisabled()
})
