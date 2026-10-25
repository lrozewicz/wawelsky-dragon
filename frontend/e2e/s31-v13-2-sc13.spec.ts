// SC-V13-13 (work/wp/V13/SCENARIOS.md, brief V13-2 T1a + KOREKTA TL): plik nieobsługiwanego
// typu — TEN SAM komunikat niezależnie od drogi. EN „Unsupported file type: setup.exe”,
// PL „Nieobsługiwany typ pliku: setup.exe” — w dialogu uploadu bazy (k1/k2) i w menedżerze
// plików `/files` (k3). W `/files` sam upload PRZYJMUJE każdy plik (pozycja „Przesłano”,
// magazyn plików nie sprawdza typu — RAGFlow); błąd przychodzi dopiero przy „Połącz z
// datasetem”: trasa linku zwraca 102 „file type not supported: setup.exe” (empiria T5b).
// Wzorce: s28-v12-messages.spec.ts (upload .exe, setProfileLanguage), s15-upload-dnd.spec.ts
// (drop prawdziwym DataTransfer, strefy `upload-dropzone`/`files-upload-dropzone`), s13-files
// (akcja wiersza „Połącz z datasetem”).
import type { Locator, Page } from '@playwright/test'

import { expect, test } from './fixtures'
import { apiLogin, createDataset } from './helpers'
import { dropFile } from './helpers/dnd'
import { deleteAllFiles, deleteDataset } from './helpers/files'
import { expectNoLayoutDefects } from './helpers/layout'
import { setProfileLanguage } from './helpers/models'
import { uiSession } from './helpers/session'

const SHOTS = process.env.WD_SHOTS_DIR ?? ''

const session = uiSession('s31-v13-2-sc13')
test.use({ storageState: session.statePath, colorScheme: 'light' })
test.setTimeout(180_000)

const VIEWPORT_WIDE = { width: 1280, height: 800 }
const EXE_NAME = 'setup.exe'
// MIME z briefu; backend odrzuca po sufiksie (INVENTORY w. 1), nie po typie MIME.
const EXE_MIME = 'application/x-msdownload'
// Prawdziwy plik z bajtami (nagłówek MZ pliku PE + wypełnienie), nie pustka.
const EXE_BYTES = Buffer.concat([Buffer.from('MZ', 'utf8'), Buffer.alloc(254, 0x77)])

let token = ''
let datasetId = ''
let datasetName = ''

test.beforeAll(async ({ browser }) => {
  await session.login(browser)
})

test.afterEach(async ({ context }) => {
  // Rotacja cookie `wd_refresh` (C9): kolejny test startuje ze ŚWIEŻYM stanem sesji.
  await session.save(context)
})

test.beforeAll(async ({ request }) => {
  test.setTimeout(240_000)
  token = await apiLogin(request)
  datasetName = `E2E S31 baza typu ${Date.now()}`
  datasetId = await createDataset(request, token, datasetName)
})

test.afterAll(async ({ request }) => {
  if (token === '') return
  // Menedżer plików jest wspólny — sprzątamy go zawsze (wzór s15).
  await deleteAllFiles(request, token)
  await deleteDataset(request, token, datasetId)
})

async function shot(page: Page, name: string): Promise<void> {
  if (SHOTS !== '') await page.screenshot({ path: `${SHOTS}/${name}.png` })
}

/** Upuszcza setup.exe w dialogu uploadu bazy i wysyła — zwraca dialog z wierszem błędu (s28). */
async function uploadExeToDataset(page: Page): Promise<Locator> {
  await page.setViewportSize(VIEWPORT_WIDE)
  await page.goto(`/dataset/files/${datasetId}`)
  await expect(page.getByRole('heading', { name: datasetName })).toBeVisible()
  await page.getByTestId('files-add').click()
  const dialog = page.getByRole('dialog')
  await expect(dialog).toBeVisible()
  await dropFile(page, dialog.getByTestId('upload-dropzone'), EXE_BYTES, EXE_NAME, EXE_MIME)
  await page.getByTestId('upload-start').click()
  return dialog
}

test('SC-V13-13 k1 UI EN: upload setup.exe w bazie — „Unsupported file type: setup.exe”', async ({
  page,
  request,
}) => {
  await setProfileLanguage(request, token, 'en')
  try {
    const dialog = await uploadExeToDataset(page)
    const alert = dialog.getByRole('alert')
    // Nowy szablon EN (CONTRACT §5, odstępstwo od DEC-356 — DEC-371); dziś: surowy tekst serwera.
    await expect(alert).toContainText('Unsupported file type: setup.exe', { timeout: 30_000 })
    await expect(alert).not.toContainText('has not been supported yet')
    await shot(page, 's31-sc13-k1-en')
    await expectNoLayoutDefects(page, 'SC-V13-13 k1: błąd uploadu setup.exe (EN)')
  } finally {
    await setProfileLanguage(request, token, 'pl')
  }
})

test('SC-V13-13 k2 UI PL: upload setup.exe w bazie — „Nieobsługiwany typ pliku: setup.exe”', async ({
  page,
}) => {
  const dialog = await uploadExeToDataset(page)
  const alert = dialog.getByRole('alert')
  // PL działa już dziś (regresja po zmianie T5): tłumaczenie z nazwą pliku, nie tekst serwera.
  await expect(alert).toContainText('Nieobsługiwany typ pliku: setup.exe', { timeout: 30_000 })
  await expect(alert).not.toContainText('has not been supported yet')
  await shot(page, 's31-sc13-k2-pl')
  await expectNoLayoutDefects(page, 'SC-V13-13 k2: błąd uploadu setup.exe (PL)')
})

test('SC-V13-13 k3: menedżer plików /files — ten sam komunikat w PL i EN', async ({
  page,
  request,
}) => {
  // PL (k3): upload w /files PRZYJMUJE plik („Przesłano” — magazyn nie sprawdza typu);
  // komunikat błędu przychodzi przy „Połącz z datasetem” (KOREKTA TL, empiria T5b).
  await setProfileLanguage(request, token, 'pl')
  await page.setViewportSize(VIEWPORT_WIDE)
  await page.goto('/files')
  await expect(page.getByRole('heading', { name: 'Pliki' })).toBeVisible()
  await page.getByTestId('files-add').click()
  await page.getByTestId('files-add-upload').click()
  const uploadDialog = page.getByRole('dialog')
  await expect(uploadDialog).toBeVisible()
  // W menedżerze drop startuje wysyłkę od razu (bez „Prześlij”) — wzór s15 B.
  await dropFile(page, page.getByTestId('files-upload-dropzone'), EXE_BYTES, EXE_NAME, EXE_MIME)
  const item = uploadDialog.getByTestId('files-upload-item-0')
  await expect(item).toBeVisible()
  await expect(item.getByText('Przesłano', { exact: true })).toBeVisible()
  await page.getByTestId('files-upload-close').click()
  await expect(uploadDialog).toBeHidden()

  // „Połącz z datasetem” na wierszu setup.exe — błąd serwera w Alert okna linku.
  const row = page.getByRole('row').filter({ hasText: EXE_NAME })
  await expect(row).toBeVisible()
  await row.getByRole('button', { name: 'Połącz z datasetem' }).click()
  const linkDialog = page.getByRole('dialog')
  await expect(linkDialog).toBeVisible()
  await linkDialog.getByRole('checkbox', { name: datasetName }).check()
  await linkDialog.getByTestId('files-link-confirm').click()
  await expect(linkDialog.getByRole('alert')).toContainText('Nieobsługiwany typ pliku: setup.exe', {
    timeout: 30_000,
  })
  await expect(linkDialog.getByRole('alert')).not.toContainText('file type not supported')
  await expect(linkDialog.getByRole('alert')).not.toContainText('has not been supported yet')
  await shot(page, 's31-sc13-k3-pl')
  await linkDialog.getByRole('button', { name: 'Anuluj' }).click()
  await expect(linkDialog).toBeHidden()

  // EN (k3): ten sam plik i ta sama droga — komunikat po angielsku.
  await setProfileLanguage(request, token, 'en')
  try {
    await page.goto('/files')
    await expect(page.getByRole('heading', { name: 'Files' })).toBeVisible()
    const enRow = page.getByRole('row').filter({ hasText: EXE_NAME })
    await expect(enRow).toBeVisible()
    await enRow.getByRole('button', { name: 'Link to dataset' }).click()
    const enLinkDialog = page.getByRole('dialog')
    await expect(enLinkDialog).toBeVisible()
    await enLinkDialog.getByRole('checkbox', { name: datasetName }).check()
    await enLinkDialog.getByTestId('files-link-confirm').click()
    await expect(enLinkDialog.getByRole('alert')).toContainText(
      'Unsupported file type: setup.exe',
      {
        timeout: 30_000,
      },
    )
    await expect(enLinkDialog.getByRole('alert')).not.toContainText('file type not supported')
    await expect(enLinkDialog.getByRole('alert')).not.toContainText('has not been supported yet')
    await shot(page, 's31-sc13-k3-en')
    await expectNoLayoutDefects(page, 'SC-V13-13 k3: błąd linku w menedżerze plików (EN)')
    await enLinkDialog.getByRole('button', { name: 'Cancel' }).click()
    await expect(enLinkDialog).toBeHidden()
  } finally {
    await setProfileLanguage(request, token, 'pl')
  }
})
