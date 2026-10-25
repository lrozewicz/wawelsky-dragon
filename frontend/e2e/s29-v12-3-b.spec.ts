// SC-V12-02 (work/wp/V12/SCENARIOS.md): import zwykłego ZIP-a mówi prawdę — UI mapuje błędy
// walidacji paczki WYŁĄCZNIE po `code` (K20 §2): `not_a_package` (JEDEN komunikat, bez nazw
// obcych plików, po języku UI), `unexpected_entry` i `unsafe_path` (komunikaty API z nazwą
// wpisu — bez nadpisywania). Wzorce: s27-e67z2-e.spec.ts (SC-E67-z2-20: prawdziwy drop),
// s26-e67a-import.spec.ts (wariant EN przez język profilu).
import type { APIRequestContext, Locator, Page } from '@playwright/test'

import { expect, test } from './fixtures'
import { apiLogin } from './helpers'
import { dropFile } from './helpers/dnd'
import { buildWdkbZip, zipStore } from './helpers/kbTransfer'
import { expectNoLayoutDefects } from './helpers/layout'
import { setProfileLanguage } from './helpers/models'
import { uiSession } from './helpers/session'

const DESKTOP = { width: 1280, height: 800 }
const MOBILE = { width: 390, height: 844 }
const SHOTS = process.env.WD_SHOTS_DIR ?? ''

const session = uiSession('s29-v12-3-b')
test.use({ storageState: session.statePath, colorScheme: 'light' })
test.setTimeout(180_000)
test.beforeAll(async ({ browser }) => {
  await session.login(browser)
})

let adminTokenPromise: Promise<string> | undefined
function adminToken(request: APIRequestContext): Promise<string> {
  adminTokenPromise ??= apiLogin(request)
  return adminTokenPromise
}

test.afterEach(async ({ context }) => {
  await session.save(context)
})

test.afterAll(async ({ request }) => {
  // Wariant EN zmienia język konta admina — przywracamy PL dla dalszych plików biegu (wzór s26).
  await setProfileLanguage(request, await adminToken(request), 'pl').catch(() => undefined)
})

async function shot(page: Page, name: string): Promise<void> {
  if (SHOTS !== '') await page.screenshot({ path: `${SHOTS}/${name}.png` })
}

/** Upuszcza paczkę w dialogu importu i zwraca dialog z listą błędów walidacji (`state=invalid`). */
async function dropPackage(
  page: Page,
  bytes: Buffer,
  name: string,
  importLabel: string,
  dialogName: string,
): Promise<{ dialog: Locator; invalid: Locator }> {
  await page.goto('/datasets')
  const importButton = page.getByRole('button', { name: importLabel })
  await expect(importButton).toBeVisible()
  await importButton.click()
  const dialog = page.getByRole('dialog', { name: dialogName })
  await expect(dialog).toBeVisible()
  await dropFile(page, dialog.getByTestId('kb-import-dropzone'), bytes, name, 'application/zip')
  const invalid = dialog.getByTestId('kb-import-invalid')
  await expect(invalid).toBeVisible({ timeout: 60_000 })
  await expectNoLayoutDefects(page, 'SC-V12-02 lista błędów paczki')
  return { dialog, invalid }
}

/** Zamyka dialog „Anuluj”/„Cancel”: faza błędów porzuca sesję importu (DELETE). */
async function cancelDialog(dialog: Locator): Promise<void> {
  await dialog.getByRole('button', { name: /Anuluj|Cancel/ }).click()
  await expect(dialog).toBeHidden()
}

// --- SC-V12-02 krok 1: ZIP bez manifest.json ----------------------------------------------------

test('SC-V12-02 (1) ZIP bez manifest.json — jeden komunikat not_a_package, bez nazw obcych plików (390)', async ({
  page,
}) => {
  await page.setViewportSize(MOBILE)
  const zip = zipStore([
    { name: 'zdjecie1.jpg', data: Buffer.from('jpg-1', 'utf8') },
    { name: 'zdjecie2.jpg', data: Buffer.from('jpg-2', 'utf8') },
  ])
  const { dialog, invalid } = await dropPackage(
    page,
    zip,
    'zdjecia.wdkb.zip',
    'Importuj',
    'Importuj bazę wiedzy',
  )
  await shot(page, 'v12-02-nomanifest-390')
  await expect(invalid.getByRole('alert'), 'dokładnie jeden komunikat').toHaveCount(1)
  await expect(invalid).toContainText(
    'To nie jest paczka bazy wiedzy Wawelsky Dragon (brak pliku manifest.json).',
  )
  await expect(invalid).not.toContainText('zdjecie1.jpg')
  await expect(invalid).not.toContainText('zdjecie2.jpg')
  await cancelDialog(dialog)
})

test('SC-V12-02 (1) EN: ten sam ZIP bez manifest.json — komunikat z locale, nie surowy z API', async ({
  page,
  request,
}) => {
  await setProfileLanguage(request, await adminToken(request), 'en')
  await page.setViewportSize(DESKTOP)
  const zip = zipStore([{ name: 'photo.jpg', data: Buffer.from('jpg', 'utf8') }])
  const { dialog, invalid } = await dropPackage(
    page,
    zip,
    'photos.wdkb.zip',
    'Import',
    'Import knowledge base',
  )
  await shot(page, 'v12-02-nomanifest-en-1280')
  await expect(invalid).toContainText(
    'This is not a Wawelsky Dragon knowledge base package (manifest.json is missing).',
  )
  await expect(invalid).not.toContainText('To nie jest paczka')
  await cancelDialog(dialog)
  // Od razu przywracamy PL — bez tego kolejne testy (PL) startują z kontem w języku EN
  // i czekają na przycisk „Importuj”, którego przez cały czas widoczności nie ma (flak).
  await setProfileLanguage(request, await adminToken(request), 'pl')
})

// --- SC-V12-02 krok 2: poprawna paczka z dopisanym notatka.txt ----------------------------------

test('SC-V12-02 (2) dopisany notatka.txt — unexpected_entry z nazwą wpisu, bez „manifest”', async ({
  page,
}) => {
  await page.setViewportSize(DESKTOP)
  const zip = buildWdkbZip({
    datasetName: `SC-V12-02 notatka ${Date.now()}`,
    extraEntries: [
      { name: 'notatka.txt', data: Buffer.from('obcy plik dopisany do paczki', 'utf8') },
    ],
  })
  const { dialog, invalid } = await dropPackage(
    page,
    zip,
    'z-notatka.wdkb.zip',
    'Importuj',
    'Importuj bazę wiedzy',
  )
  await shot(page, 'v12-02-unexpected-1280')
  await expect(invalid).toContainText('Nieoczekiwany wpis „notatka.txt” w paczce')
  await expect(invalid).toContainText('notatka.txt')
  await expect(invalid, 'bez mylącego komunikatu o manifeście').not.toContainText('manifest')
  await cancelDialog(dialog)
})

// --- SC-V12-02 krok 3: wpis ../x ----------------------------------------------------------------

test('SC-V12-02 (3) wpis ../x — unsafe_path, komunikat API z nazwą wpisu', async ({ page }) => {
  await page.setViewportSize(DESKTOP)
  const zip = buildWdkbZip({
    datasetName: `SC-V12-02 unsafe ${Date.now()}`,
    extraEntries: [{ name: '../x', data: Buffer.from('x', 'utf8') }],
  })
  const { dialog, invalid } = await dropPackage(
    page,
    zip,
    'niebezpieczna.wdkb.zip',
    'Importuj',
    'Importuj bazę wiedzy',
  )
  await shot(page, 'v12-02-unsafe-1280')
  await expect(invalid).toContainText('Niebezpieczna ścieżka wpisu „../x”')
  await cancelDialog(dialog)
})
