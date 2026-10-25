// SC-V12-06 k.4 (work/wp/V12/SCENARIOS.md) + QA V12-2-1 defekt D1 (MAJOR): import paczki z
// błędem walidacji w UI EN — komunikat po angielsku z locale (mapowanie WYŁĄCZNIE po `code`,
// K20 §5 p. 2), a polski komunikat serwera tylko w zwiniętym bloku „Technical details”;
// oraz zmiana nazwy bazy na istniejącą w PL — komunikat serwera przetłumaczony przez
// `lib/serverMessages` („Zbiór o nazwie „X” już istnieje”), nie surowy angielski.
// Wzorce: s29-v12-3-b.spec.ts (upuszczenie paczki, wariant EN przez język profilu),
// s27-e67z2-e.spec.ts (menu karty bazy, sprzątanie baz).
import type { APIRequestContext, Locator, Page } from '@playwright/test'

import { expect, test } from './fixtures'
import { apiLogin, createDataset } from './helpers'
import { dropFile } from './helpers/dnd'
import { deleteDataset } from './helpers/files'
import { buildWdkbZip } from './helpers/kbTransfer'
import { expectNoLayoutDefects } from './helpers/layout'
import { setProfileLanguage } from './helpers/models'
import { uiSession } from './helpers/session'

const DESKTOP = { width: 1280, height: 800 }
const MOBILE = { width: 390, height: 844 }
const SHOTS = process.env.WD_SHOTS_DIR ?? ''

const session = uiSession('s29-v12-3-c')
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

const cleanupDatasets: string[] = []
test.afterEach(async ({ context }) => {
  await session.save(context)
})

test.afterAll(async ({ request }) => {
  // Wariant EN zmienia język konta admina — przywracamy PL dla dalszych plików biegu (wzór s29-b).
  await setProfileLanguage(request, await adminToken(request), 'pl').catch(() => undefined)
  const token = await adminToken(request)
  for (const id of cleanupDatasets.splice(0)) await deleteDataset(request, token, id)
})

async function shot(page: Page, name: string): Promise<void> {
  if (SHOTS !== '') await page.screenshot({ path: `${SHOTS}/${name}.png` })
}

/** Upuszcza paczkę w dialogu importu i zwraca kontener listy błędów walidacji (`state=invalid`). */
async function dropPackage(
  page: Page,
  bytes: Buffer,
  name: string,
  importLabel: string,
  dialogName: string,
): Promise<Locator> {
  await page.goto('/datasets')
  const importButton = page.getByRole('button', { name: importLabel })
  await expect(importButton).toBeVisible()
  await importButton.click()
  const dialog = page.getByRole('dialog', { name: dialogName })
  await expect(dialog).toBeVisible()
  await dropFile(page, dialog.getByTestId('kb-import-dropzone'), bytes, name, 'application/zip')
  const invalid = dialog.getByTestId('kb-import-invalid')
  await expect(invalid).toBeVisible({ timeout: 60_000 })
  return invalid
}

/** Zamyka dialog „Anuluj”/„Cancel”: faza błędów porzuca sesję importu (DELETE). */
async function cancelDialog(dialog: Locator): Promise<void> {
  await dialog.getByRole('button', { name: /Anuluj|Cancel/ }).click()
  await expect(dialog).toBeHidden()
}

// --- SC-V12-06 k.4: import paczki z błędnym manifestem, UI EN ------------------------------------

test('SC-V12-06 k.4 EN: manifest bez embedding.included — komunikat z locale, szczegół serwera zwinięty (390)', async ({
  page,
  request,
}) => {
  await setProfileLanguage(request, await adminToken(request), 'en')
  await page.setViewportSize(MOBILE)
  const zip = buildWdkbZip({
    datasetName: `SC-V12-06 manifest ${Date.now()}`,
    // Walidacja pydantic pada na braku wymaganego pola: „Niepoprawny manifest — pole
    // embedding.included: Field required” (QA V12-2-1 D1).
    manifestOverride: (manifest) => {
      const embedding = manifest.embedding as Record<string, unknown>
      delete embedding.included
      return manifest
    },
  })
  const invalid = await dropPackage(
    page,
    zip,
    'zly-manifest.wdkb.zip',
    'Import',
    'Import knowledge base',
  )
  await shot(page, 'v12-06-manifest-en-390')

  const alert = invalid.getByRole('alert')
  await expect(alert, 'przyczyna po `code`, po angielsku').toHaveCount(1)
  await expect(alert).toContainText('The package has an invalid manifest.')
  // Polski komunikat serwera NIE jest tekstem Alertu — czeka w zwiniętym bloku szczegółów
  // (natywne `<details>`: zwinięty = brak atrybutu `open`, treść niewidoczna dla użytkownika).
  const details = invalid.getByTestId('kb-import-error-details')
  await expect(invalid.getByText('Technical details')).toBeVisible()
  await expect(details, 'szczegół serwera domyślnie zwinięty').not.toHaveAttribute('open')
  await expectNoLayoutDefects(page, 'SC-V12-06 k.4 EN błąd importu (zwinięty, 390)')

  await invalid.getByText('Technical details').click()
  await expect(details, 'kliknięcie rozwija blok').toHaveAttribute('open')
  await expect(
    invalid.getByText('Niepoprawny manifest — pole embedding.included: Field required'),
    'kliknięcie odsłania komunikat serwera',
  ).toBeVisible()
  await shot(page, 'v12-06-manifest-en-390-details')
  await expectNoLayoutDefects(page, 'SC-V12-06 k.4 EN szczegóły rozwinięte (390)')
  await cancelDialog(page.getByRole('dialog', { name: 'Import knowledge base' }))
  // Od razu przywracamy PL — bez tego kolejne testy (PL) startują z kontem w języku EN (flak).
  await setProfileLanguage(request, await adminToken(request), 'pl')
})

test('SC-V12-06 k.4 EN: unexpected_entry — tytuł z locale, nazwa wpisu w bloku szczegółów (1280)', async ({
  page,
  request,
}) => {
  await setProfileLanguage(request, await adminToken(request), 'en')
  await page.setViewportSize(DESKTOP)
  const zip = buildWdkbZip({
    datasetName: `SC-V12-06 notatka EN ${Date.now()}`,
    extraEntries: [
      { name: 'notatka.txt', data: Buffer.from('obcy plik dopisany do paczki', 'utf8') },
    ],
  })
  const invalid = await dropPackage(
    page,
    zip,
    'z-notatka.wdkb.zip',
    'Import',
    'Import knowledge base',
  )
  await shot(page, 'v12-06-unexpected-en-1280')

  await expect(invalid).toContainText(
    'The package contains a file that is not listed in the manifest.',
  )
  const details = invalid.getByTestId('kb-import-error-details')
  await expect(details, 'szczegół serwera z nazwą wpisu zwinięty').not.toHaveAttribute('open')
  await invalid.getByText('Technical details').click()
  await expect(details).toHaveAttribute('open')
  await expect(invalid.getByText('Nieoczekiwany wpis „notatka.txt” w paczce')).toBeVisible()
  await expectNoLayoutDefects(page, 'SC-V12-06 k.4 EN unexpected_entry (1280)')
  await cancelDialog(page.getByRole('dialog', { name: 'Import knowledge base' }))
  await setProfileLanguage(request, await adminToken(request), 'pl')
})

// --- SC-V12-06: zmiana nazwy bazy na istniejącą, UI PL -------------------------------------------

test('SC-V12-06 zmiana nazwy bazy na istniejącą — komunikat po polsku przy polu nazwy (1280)', async ({
  page,
  request,
}) => {
  const token = await adminToken(request)
  const nameA = `SC-V12-06 rename A ${Date.now()}`
  const nameB = `SC-V12-06 rename B ${Date.now()}`
  cleanupDatasets.push(await createDataset(request, token, nameA))
  cleanupDatasets.push(await createDataset(request, token, nameB))

  await page.setViewportSize(DESKTOP)
  await page.goto('/datasets')
  await page.getByRole('button', { name: `Menu bazy wiedzy ${nameA}` }).click()
  await page.getByRole('menuitem', { name: 'Zmień nazwę' }).click()
  const dialog = page.getByRole('dialog')
  await expect(dialog).toBeVisible()
  await dialog.getByRole('textbox').fill(nameB)
  await dialog.getByRole('button', { name: 'Zapisz' }).click()

  const alert = dialog.getByRole('alert')
  await expect(alert).toContainText(`Zbiór o nazwie „${nameB}” już istnieje`)
  await expect(alert, 'surowy komunikat serwera przetłumaczony').not.toContainText(
    `Dataset name '${nameB}' already exists`,
  )
  await shot(page, 'v12-06-rename-duplicate-1280')
  await expectNoLayoutDefects(page, 'SC-V12-06 zmiana nazwy na istniejącą (1280)')
})
