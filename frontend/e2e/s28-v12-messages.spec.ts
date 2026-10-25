// Scenariusze SC-V12-06 (kroki 1–4) i SC-V12-09 (kroki 1–2) z work/wp/V12/SCENARIOS.md, brief T3b:
// komunikaty serwera i log parsowania w języku interfejsu (K20 §5 p. 1 i 4; INVENTORY WP V12-2).
// Testy tłumaczeń pisane PRZED wpięciem (czerwone z właściwej przyczyny); testy oznaczone
// „regresja” (EN 1:1, komunikat spoza tabeli, brak wpisu „Auto metadata”, import paczki)
// są zielone i przed, i po zmianie — pilnują, by wpięcie niczego nie psuło.
// Wzorzec: s27-e67z2-f.spec.ts (sesja) i s15-upload-dnd.spec.ts (drop prawdziwym DataTransfer).
import { mkdtempSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import path from 'node:path'

import { expect, test } from './fixtures'
import { apiLogin, createDataset, seedCorpus } from './helpers'
import type { SeededCorpus } from './helpers'
import { deleteDataset } from './helpers/files'
import { dropFile } from './helpers/dnd'
import { expectNoLayoutDefects } from './helpers/layout'
import { setProfileLanguage } from './helpers/models'
import { uiSession } from './helpers/session'

const SHOTS = process.env.WD_SHOTS_DIR ?? ''

const session = uiSession('s28-v12-messages')
test.use({ storageState: session.statePath, colorScheme: 'light' })
test.setTimeout(240_000)

const DATASET_NAME = 'E2E V12-2 T3b komunikaty'
const EXE_NAME = 'x.exe'
// Plik „wykonywalny” tylko z nazwy — backend odrzuca po rozszerzeniu (INVENTORY w. 1, kod 500).
const EXE_BYTES = Buffer.from(
  'MZ — fejkowy plik .exe dla SC-V12-06 k1 (odrzucany po sufiksie).',
  'utf8',
)

// Wpis progress_msg tak, jak pisze go worker (INVENTORY P1, P14, P21 + linia spoza tabeli).
const INJECTED_LOG = [
  '08:00:01 Task has been received.',
  '08:00:02 Auto metadata: 0 fields',
  '08:00:03 Auto metadata: 2 fields',
  '08:00:04 [ERROR] File is corrupted or unreadable (.xlsx): broken zip',
  '08:00:05 całkiem nieznany wpis 42',
].join('\n')

let token = ''
let datasetId = ''
let corpus: SeededCorpus
let exePath = ''
let tmpDir = ''

// Logowanie w OSOBNYM haku PRZED hakiem używającym `request`: fixture `request` jest składany
// z opcji `test.use` i czyta `storageState` — plik powstaje dopiero w `session.login` (pułapka
// z s17b: ENOENT wywala hak przed ciałem, bez komunikatu).
test.beforeAll(async ({ browser }) => {
  await session.login(browser)
})

test.beforeAll(async ({ request }) => {
  token = await apiLogin(request)
  datasetId = await createDataset(request, token, DATASET_NAME)
  corpus = await seedCorpus(request, token, {
    datasetName: `E2E V12-2 T3b log ${Date.now()}`,
    documentName: 'e2e-t3b-notatka.txt',
    documentBody: 'Notatka służbowa do scenariusza logu parsowania SC-V12-09 krok 1.',
  })
  tmpDir = mkdtempSync(path.join(tmpdir(), 'wd-t3b-'))
  exePath = path.join(tmpDir, EXE_NAME)
  writeFileSync(exePath, EXE_BYTES)
})

test.afterAll(async ({ request }) => {
  rmSync(tmpDir, { force: true, recursive: true })
  await deleteDataset(request, token, datasetId)
  await deleteDataset(request, token, corpus.datasetId)
})

test.afterEach(async ({ context }) => {
  await session.save(context)
})

async function shot(page: import('@playwright/test').Page, name: string): Promise<void> {
  if (SHOTS !== '') await page.screenshot({ path: `${SHOTS}/${name}.png` })
}

/**
 * Dialog logu parsowania rozpoznawany po nazwie dokumentu — tytuł jest w języku UI
 * („Log parsowania — …” / „Parsing log — …”), nazwa pliku go rozstrzyga.
 */
function logDialogName(): RegExp {
  return new RegExp(`— ${corpus.documentName.replace(/\./g, '\\.')}$`)
}

/** Koperta RAGFlow zwracana przez przechwyconą trasę (HTTP 200 — błędy idą w `code`). */
function envelope(code: number, message: string): string {
  return JSON.stringify({ code, message, data: null })
}

/**
 * Otwiera dialog przesyłania plików i wysyła plik .exe (k1): `how = 'pick'` — prawdziwy plik
 * z dysku przez `setInputFiles` na `upload-input`; `how = 'drop'` — prawdziwy `DataTransfer`
 * na `upload-dropzone` (wzorzec s15). Zwraca dialog z wierszem błędu.
 */
async function uploadExe(
  page: import('@playwright/test').Page,
  how: 'pick' | 'drop',
): Promise<import('@playwright/test').Locator> {
  await page.goto(`/dataset/files/${datasetId}`)
  await page.getByRole('heading', { name: DATASET_NAME }).waitFor()
  await page.getByTestId('files-add').click()
  const dialog = page.getByRole('dialog')
  await expect(dialog).toBeVisible()
  if (how === 'pick') {
    await dialog.getByTestId('upload-input').setInputFiles(exePath)
  } else {
    await dropFile(
      page,
      dialog.getByTestId('upload-dropzone'),
      EXE_BYTES,
      EXE_NAME,
      'application/octet-stream',
    )
  }
  await page.getByTestId('upload-start').click()
  return dialog
}

test('SC-V12-06 k1 UI PL: upload .exe (wybór z dysku) — przyczyna po polsku, nie tekst serwera', async ({
  page,
}) => {
  test.setTimeout(120_000)
  await page.setViewportSize({ width: 1280, height: 800 })
  const dialog = await uploadExe(page, 'pick')
  const alert = dialog.getByRole('alert')
  await expect(alert).toContainText('Nieobsługiwany typ pliku: x.exe', { timeout: 30_000 })
  await expect(alert).not.toContainText('This type of file has not been supported yet')
  await shot(page, 'sc06-upload-pl-1280')
  await shot(page, 'desktop')
  await expectNoLayoutDefects(page, 'SC-V12-06 k1: wiersz błędu uploadu (PL, 1280)')
})

test('SC-V12-06 k1 UI PL: upload .exe dropem (DataTransfer) — przyczyna po polsku', async ({
  page,
}) => {
  test.setTimeout(120_000)
  await page.setViewportSize({ width: 1280, height: 800 })
  const dialog = await uploadExe(page, 'drop')
  const alert = dialog.getByRole('alert')
  await expect(alert).toContainText('Nieobsługiwany typ pliku: x.exe', { timeout: 30_000 })
  await expect(alert).not.toContainText('This type of file has not been supported yet')
})

test('SC-V12-06 k1 UI PL 390: wiersz błędu mieści się w oknie dialogu', async ({ page }) => {
  test.setTimeout(120_000)
  await page.setViewportSize({ width: 390, height: 844 })
  const dialog = await uploadExe(page, 'pick')
  const alert = dialog.getByRole('alert')
  await expect(alert).toContainText('Nieobsługiwany typ pliku: x.exe', { timeout: 30_000 })
  await shot(page, 'sc06-upload-pl-390')
  await shot(page, 'mobile')
  await expectNoLayoutDefects(page, 'SC-V12-06 k1: wiersz błędu uploadu (PL, 390)')
})

test('SC-V12-06 k1 UI PL (ciemny): wiersz błędu czytelny w ciemnym motywie', async ({ page }) => {
  test.setTimeout(120_000)
  await page.emulateMedia({ colorScheme: 'dark' })
  await page.setViewportSize({ width: 1280, height: 800 })
  const dialog = await uploadExe(page, 'pick')
  const alert = dialog.getByRole('alert')
  await expect(alert).toContainText('Nieobsługiwany typ pliku: x.exe', { timeout: 30_000 })
  await shot(page, 'sc06-upload-pl-dark-1280')
  await expectNoLayoutDefects(page, 'SC-V12-06 k1: wiersz błędu uploadu (PL, ciemny)')
})

test('SC-V12-06 k1 UI EN: upload .exe — komunikat ujednolicony z PL (DEC-371)', async ({
  page,
  request,
}) => {
  test.setTimeout(120_000)
  await setProfileLanguage(request, token, 'en')
  try {
    await page.setViewportSize({ width: 1280, height: 800 })
    const dialog = await uploadExe(page, 'pick')
    const alert = dialog.getByRole('alert')
    await expect(alert).toContainText('Unsupported file type: x.exe', {
      timeout: 30_000,
    })
    await expect(alert).not.toContainText('This type of file has not been supported yet')
    await shot(page, 'sc06-upload-en-1280')
  } finally {
    await setProfileLanguage(request, token, 'pl')
  }
})

test('SC-V12-06 k2 UI PL: konfiguracja datasetu — odrzucenie serwera po polsku przy polu', async ({
  page,
}) => {
  await page.setViewportSize({ width: 1280, height: 800 })
  // Realna walidacja nie ma jak wywołać (UI proponuje tylko poprawne metody) — odrzucenie
  // wymusza `page.route` na PUT datasetu z kopertą wiersza 12 INVENTORY (kod 101).
  await page.route(/\/api\/v1\/datasets\/[^/]+$/, (route) => {
    if (route.request().method() !== 'PUT') return route.continue()
    return route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: envelope(101, '`chunk_method` foo is not supported by Wawelsky Dragon'),
    })
  })
  await page.goto(`/dataset/configuration/${datasetId}`)
  await expect(page.getByRole('heading', { name: DATASET_NAME })).toBeVisible()
  // Bez `exact`: pole `required` ma w etykiecie MUI gwiazdkę („Nazwa *”).
  await page.getByLabel('Nazwa').fill(`Zmieniona ${Date.now()}`)
  await page.getByRole('button', { name: 'Zapisz' }).click()
  const alert = page.getByRole('alert')
  await expect(alert).toContainText(
    'Metoda chunkowania foo nie jest obsługiwana przez Wawelsky Dragon',
  )
  await expect(alert).not.toContainText('not supported by')
  // Zrzut z komunikatem w kadrze — Alert wisi u góry długiego formularza.
  await alert.scrollIntoViewIfNeeded()
  await shot(page, 'sc06-config-alert-pl-1280')
  await expectNoLayoutDefects(page, 'SC-V12-06 k2: komunikat odrzucenia konfiguracji (PL)')
})

test('SC-V12-06 k. „spoza tabeli” UI PL: nieznany komunikat pokazany dosłownie', async ({
  page,
}) => {
  await page.setViewportSize({ width: 1280, height: 800 })
  await page.route(/\/api\/v1\/datasets\/[^/]+$/, (route) => {
    if (route.request().method() !== 'PUT') return route.continue()
    return route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: envelope(102, 'coś nieznanego'),
    })
  })
  await page.goto(`/dataset/configuration/${datasetId}`)
  await expect(page.getByRole('heading', { name: DATASET_NAME })).toBeVisible()
  await page.getByLabel('Nazwa').fill(`Inna nazwa ${Date.now()}`)
  await page.getByRole('button', { name: 'Zapisz' }).click()
  const alert = page.getByRole('alert')
  await expect(alert).toContainText('coś nieznanego')
  // Ani ogólnik serwera ani generyk UI — dokładnie treść z koperty.
  await expect(alert).not.toContainText('Nieznany')
  await expect(alert).not.toContainText('Nie udało się zapisać')
})

test('SC-V12-06 k3 UI PL: log parsowania — wpisy P1/P14/P21 przetłumaczone, czas zachowany', async ({
  page,
}) => {
  await page.setViewportSize({ width: 1280, height: 800 })
  await page.route(/\/api\/v1\/datasets\/[^/]+\/documents\?/, async (route) => {
    const response = await route.fetch()
    const body = (await response.json()) as { data: { docs: { progress_msg: string }[] } }
    for (const doc of body.data.docs) doc.progress_msg = INJECTED_LOG
    await route.fulfill({ response, json: body })
  })
  await page.goto(`/dataset/files/${corpus.datasetId}`)
  await page.getByTestId(`status-log-${corpus.documentId}`).click()
  const logDialog = page.getByRole('dialog', { name: logDialogName() })
  await expect(logDialog).toBeVisible()
  // P1 i P14 (CONTRACT (c): „0 fields” = nie znaleziono wartości; 2 → „2 pola”).
  await expect(logDialog).toContainText('08:00:01 Zadanie przyjęte.')
  await expect(logDialog).toContainText('Metadane automatyczne: nie znaleziono wartości')
  await expect(logDialog).not.toContainText('Auto metadata: 0 fields')
  await expect(logDialog).toContainText('Metadane automatyczne: 2 pola')
  await expect(logDialog).not.toContainText('Auto metadata: 2 fields')
  // P21 z prefiksem czasu i „[ERROR] ” (P18) — czas i etykieta nie tłumaczone.
  await expect(logDialog).toContainText(
    '08:00:04 [ERROR] Plik jest uszkodzony lub nieczytelny (.xlsx): broken zip',
  )
  // Linia spoza tabeli — dosłownie.
  await expect(logDialog).toContainText('08:00:05 całkiem nieznany wpis 42')
  await expect(logDialog).not.toContainText('Task has been received.')
  await shot(page, 'sc06-log-pl-1280')
  await expectNoLayoutDefects(page, 'SC-V12-06 k3: dialog logu parsowania (PL)')
})

test('SC-V12-06 k3 UI EN: log parsowania — „Auto metadata: 0 fields” → „no values found”', async ({
  page,
  request,
}) => {
  await page.setViewportSize({ width: 1280, height: 800 })
  await setProfileLanguage(request, token, 'en')
  try {
    await page.route(/\/api\/v1\/datasets\/[^/]+\/documents\?/, async (route) => {
      const response = await route.fetch()
      const body = (await response.json()) as { data: { docs: { progress_msg: string }[] } }
      for (const doc of body.data.docs) doc.progress_msg = '08:00:02 Auto metadata: 0 fields'
      await route.fulfill({ response, json: body })
    })
    await page.goto(`/dataset/files/${corpus.datasetId}`)
    await page.getByTestId(`status-log-${corpus.documentId}`).click()
    const logDialog = page.getByRole('dialog', { name: logDialogName() })
    await expect(logDialog).toBeVisible()
    // EN ma własny klucz (CONTRACT (c)) — surowy wpis „0 fields” nie może przejść 1:1.
    await expect(logDialog).toContainText('08:00:02 Auto metadata: no values found')
    await expect(logDialog).not.toContainText('Auto metadata: 0 fields')
  } finally {
    await setProfileLanguage(request, token, 'pl')
  }
})

test('SC-V12-06 k4 (regresja) UI EN: import paczki z błędem walidacji — komunikat po angielsku', async ({
  page,
  request,
}) => {
  test.setTimeout(300_000)
  await setProfileLanguage(request, token, 'en')
  try {
    await page.setViewportSize({ width: 1280, height: 800 })
    await page.goto('/datasets')
    await page.getByRole('button', { name: 'Import' }).click()
    const dialog = page.getByRole('dialog', { name: 'Import knowledge base' })
    await expect(dialog).toBeVisible()
    // Plik tekstowy przemianowany na .wdkb.zip → serwer odrzuca (`invalid_archive`); UI mapuje
    // po `code` (features/kb-transfer/errors.ts — bez zmian w tym zadaniu) na tekst EN.
    await dialog.locator('input[type="file"]').setInputFiles({
      name: 'nie-paczka.wdkb.zip',
      mimeType: 'application/zip',
      buffer: Buffer.from('To nie jest archiwum ZIP — SC-V12-06 k4.', 'utf8'),
    })
    await expect(
      dialog.getByText('This is not a valid knowledge base package (.wdkb.zip).'),
      'komunikat walidacji po angielsku',
    ).toBeVisible({ timeout: 60_000 })
    await shot(page, 'sc06-import-en-1280')
    await dialog.getByRole('button', { name: 'Cancel' }).click()
    await expect(dialog).toBeHidden()
  } finally {
    await setProfileLanguage(request, token, 'pl')
  }
})

test('SC-V12-09 k1 (regresja): dataset bez pól metadanych — w logu brak linii „Auto metadata”', async ({
  page,
}) => {
  await page.setViewportSize({ width: 1280, height: 800 })
  await page.goto(`/dataset/files/${corpus.datasetId}`)
  const row = page.getByRole('row', { name: new RegExp(corpus.documentName) })
  await expect(row).toContainText('Sukces', { timeout: 120_000 })
  await page.getByTestId(`status-log-${corpus.documentId}`).click()
  const logDialog = page.getByRole('dialog', { name: logDialogName() })
  await expect(logDialog).toBeVisible()
  // CONTRACT (c): przy braku skonfigurowanych pól backend nie pisze wpisu „Auto metadata”,
  // a UI nie ma prawa dopisywać go od siebie.
  await expect(logDialog).not.toContainText('Auto metadata')
  await expect(logDialog).not.toContainText('Metadane automatyczne')
  // Log nie jest pusty — parsowanie zostawiło po sobie wpisy.
  await expect(logDialog).toContainText(/Zadanie przyjęte\.|Task has been received\./)
  await shot(page, 'sc09-log-pl-1280')
  await expectNoLayoutDefects(page, 'SC-V12-09 k1: log parsowania bez metadanych')
})
