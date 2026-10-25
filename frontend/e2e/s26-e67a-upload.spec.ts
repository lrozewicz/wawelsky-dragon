// Scenariusz SC-E67-04 (WP E67-z1a): „Prześlij” po błędzie nie dubluje plików. Trzy pliki wpadają
// prawdziwym drag & drop (`DataTransfer`, helper z S15); trasa `POST .../documents` odrzuca jeden z nich
// (400 z kopertą błędu). Drugi klik „Prześlij” ma wysłać WYŁĄCZNIE odrzucony plik; po pełnym sukcesie
// „Prześlij” jest nieaktywne, a „Gotowe” jedynym przyciskiem głównym. Lista dokumentów bierze się
// z prawdziwego API (bez duplikatów). Parsowanie wyłączone — nie jest przedmiotem scenariusza.
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

import type { ConsoleMessage } from '@playwright/test'

import { expect, resetDb, test } from './fixtures'
import { apiLogin, createDataset, loginViaUi } from './helpers'
import { dropFile } from './helpers/dnd'
import { deleteAllFiles, deleteDataset } from './helpers/files'
import { listDatasetDocuments, takeOverConsoleGuard } from './helpers/integrations'
import { expectNoLayoutDefects } from './helpers/layout'

const DATASET_NAME = 'E2E SC-E67-04 ponowienie uploadu'
const REJECTED = 'sample.docx'
const FILES = [
  { name: 'sample.pdf', mime: 'application/pdf' },
  {
    name: REJECTED,
    mime: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  },
  {
    name: 'sample.xlsx',
    mime: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  },
]
const REASON = 'Plik odrzucony: niedozwolony typ'
const UPLOAD_TIMEOUT_MS = 60_000
const VIEWPORTS = [
  { label: 'desktop', width: 1280, height: 800 },
  { label: '390 px', width: 390, height: 844 },
]

function fixtureBytes(name: string): Buffer {
  return readFileSync(fileURLToPath(new URL(`./fixtures/${name}`, import.meta.url)))
}

/** Oczekiwany błąd konsoli: przeglądarka loguje HTTP 400 z zamockowanej trasy uploadu. */
function isMockedUpload400(message: ConsoleMessage): boolean {
  return message.text().includes('400') && message.location().url.includes('/documents')
}

let cleanup: { token: string; datasetId: string } | undefined

test.afterEach(async ({ request }) => {
  if (cleanup === undefined) return
  await deleteAllFiles(request, cleanup.token)
  await deleteDataset(request, cleanup.token, cleanup.datasetId)
  cleanup = undefined
})

for (const viewport of VIEWPORTS) {
  test(`SC-E67-04 (${viewport.label}): ponowny „Prześlij” wysyła tylko nieudany plik`, async ({
    page,
    request,
  }) => {
    test.setTimeout(180_000)
    await page.setViewportSize({ width: viewport.width, height: viewport.height })
    const consoleErrors = takeOverConsoleGuard(page, [isMockedUpload400])

    await resetDb(request)
    const token = await apiLogin(request)
    const datasetId = await createDataset(request, token, DATASET_NAME)
    cleanup = { token, datasetId }
    await loginViaUi(page)
    await page.goto(`/dataset/files/${datasetId}`)
    await expect(page.getByRole('heading', { name: DATASET_NAME })).toBeVisible()

    // Krok 1: trzy pliki dropem, serwer odrzuca jeden z nich.
    await page.getByTestId('files-add').click()
    const dialog = page.getByRole('dialog')
    await expect(dialog).toBeVisible()
    await dialog.getByTestId('upload-parse-toggle').uncheck()
    for (const file of FILES) {
      await dropFile(
        page,
        dialog.getByTestId('upload-dropzone'),
        fixtureBytes(file.name),
        file.name,
        file.mime,
      )
      await expect(dialog.getByText(file.name, { exact: true })).toBeVisible()
    }

    // Trasa zostaje przez cały test (bez niej Chromium nie udostępnia ciała multipart): zapisuje
    // nazwy wysyłanych plików i, dopóki `rejecting`, odrzuca `REJECTED` kopertą błędu.
    let rejecting = true
    let sent: string[] = []
    await page.route('**/api/v1/datasets/*/documents', async (route) => {
      const body = route.request().postDataBuffer()?.toString('latin1') ?? ''
      if (route.request().method() !== 'POST') {
        await route.fallback()
        return
      }
      for (const file of FILES) if (body.includes(`filename="${file.name}"`)) sent.push(file.name)
      if (rejecting && body.includes(`filename="${REJECTED}"`)) {
        await route.fulfill({
          status: 400,
          contentType: 'application/json',
          body: JSON.stringify({ code: 101, message: REASON, data: false }),
        })
        return
      }
      await route.fallback()
    })
    await dialog.getByTestId('upload-start').click()
    await expect(dialog.getByTestId('upload-summary')).toHaveText('Przesłano 2 z 3', {
      timeout: UPLOAD_TIMEOUT_MS,
    })
    const firstBatch = sent
    expect(firstBatch.sort()).toEqual(FILES.map((file) => file.name).sort())
    await expect(dialog.getByText('Przesłano', { exact: true })).toHaveCount(2)
    await expect(dialog.getByRole('alert').filter({ hasText: REASON })).toHaveCount(1)
    await expect(dialog.getByTestId('upload-start')).toBeEnabled()
    await expectNoLayoutDefects(page, 'dialog uploadu z błędem')
    await page.screenshot({ path: `../.task/shots/error-${String(viewport.width)}.png` })

    // Krok 2: serwer przestaje odrzucać; ponowny klik wysyła tylko odrzucony plik.
    rejecting = false
    sent = []
    await dialog.getByTestId('upload-start').click()
    await expect(dialog.getByTestId('upload-summary')).toHaveText('Przesłano 3 z 3', {
      timeout: UPLOAD_TIMEOUT_MS,
    })
    const retryBatch = sent
    expect(retryBatch, 'ponowienie wysyła wyłącznie odrzucony plik').toEqual([REJECTED])

    // Krok 3: po pełnym sukcesie „Prześlij” nieaktywne, „Gotowe” jedyny przycisk główny.
    await expect(dialog.getByTestId('upload-start')).toBeDisabled()
    await expect(dialog.getByTestId('upload-close')).toHaveText('Gotowe')
    await expect(dialog.getByRole('alert')).toHaveCount(0)
    await expectNoLayoutDefects(page, 'dialog uploadu po sukcesie')
    await page.screenshot({
      path: `../.task/shots/${viewport.width === 390 ? 'mobile' : 'desktop'}.png`,
    })

    await dialog.getByTestId('upload-close').click()
    await expect(dialog).toBeHidden()
    const names = await listDatasetDocuments(request, token, datasetId)
    expect(names.sort(), 'dokumenty datasetu bez duplikatów').toEqual(
      FILES.map((file) => file.name).sort(),
    )
    expect(consoleErrors, 'błędy konsoli').toEqual([])
  })
}
