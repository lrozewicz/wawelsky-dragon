// Scenariusze SC-E6-1b-01 i SC-E6-1b-02 (SCENARIOS.md WP E6-1b, brief T1a): konfiguracja pól
// auto-metadanych w zakładce „Konfiguracja” — sekcja „Metadane” (nagłówek, przełącznik
// „Auto-metadane”, „+ Pole”, kolumny „Klucz”/„Opis (dla modelu)”/„Dozwolone wartości”), dialog
// „Zastosować zmiany do istniejących plików?” po zapisie (R-CFG-01) oraz chipy metadanych na
// liście plików po parsowaniu z fake-llm. Na bazie (bez implementacji T2/T3/T4) testy są
// CZERWONE z właściwej przyczyny: brak sekcji „Metadane” / kolumny „Metadane” / przycisku
// „+ Pole”, nie błąd setupu — setup (logowanie, dataset, upload, auto-metadane przez API)
// dochodzi do punktu, w którym brakuje UI.
// Wzorce: s17-dataset-reconfig.spec.ts (sesja `uiSession`, memoizacja tokenu, sprzątanie,
// poll parsowania po API), s15-upload-dnd.spec.ts + helpers/dnd.ts (upload prawdziwymi
// plikami i `DataTransfer`, nie `setInputFiles`), expectNoLayoutDefects na każdym ekranie.
// Etykiety i teksty — dosłownie CONTRACT WP E6-1b §4; teksty dialogu zastosowania — z
// istniejącego `ApplyToFilesDialog` (scenariusz mówi „Parsuj ponownie istniejące”, kod ma
// „Zastosuj i parsuj ponownie (N)” — odchyłka do raportu TL).
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import type { APIRequestContext, APIResponse, Page } from '@playwright/test'

import { expect, test } from './fixtures'
import { POLL_TIMEOUT_MS, apiLogin, createDataset } from './helpers'
import { dropFile } from './helpers/dnd'
import { deleteDataset } from './helpers/files'
import { expectNoLayoutDefects } from './helpers/layout'
import { setProfileLanguage } from './helpers/models'
import { uiSession } from './helpers/session'

const API_URL = process.env.WD_E2E_API_URL ?? ''

const APPLY_TITLE = 'Zastosować zmiany do istniejących plików?'
const FIXTURE_NAME = 'metadata-rok-typ.txt'
const PDF_NAME = 'sample.pdf'
const DOCX_NAME = 'sample.docx'
const PDF_MIME = 'application/pdf'
const DOCX_MIME = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
const FIXTURE_MIME = 'text/plain'
const PDF_PATH = fileURLToPath(new URL('./fixtures/sample.pdf', import.meta.url))
const DOCX_PATH = fileURLToPath(new URL('./fixtures/sample.docx', import.meta.url))
const FIXTURE_PATH = fileURLToPath(new URL('./fixtures/metadata-rok-typ.txt', import.meta.url))

// Wariant „długie dane” (SC-01): klucz 64 znaki, opis 300 znaków, 12 dozwolonych wartości
// (ostatnia długa — dla wielokropka i `title`).
const LONG_KEY = 'k'.repeat(64)
const LONG_DESCRIPTION = 'o'.repeat(300)
const LONG_VALUE = `wartość-${'d'.repeat(34)}`
const LONG_ENUM = [
  ...Array.from({ length: 11 }, (_, index) => `wartość-${String(index + 1).padStart(2, '0')}`),
  LONG_VALUE,
]

const sleep = (ms: number): Promise<void> => new Promise((resolve) => setTimeout(resolve, ms))

/** Unikalna nazwa datasetu — reset K9 biegnie raz na bieg, sprzątanie w afterEach (wzór: s17). */
function uniq(): string {
  return `${Date.now()}-${Math.floor(Math.random() * 1_000_000)}`
}

/**
 * Współdzielony token admina na cały bieg pliku: limiter logowań liczy KAŻDĄ próbę
 * (10/min per IP+e-mail, CONTRACT E5-2a §4) — wzór: s17-dataset-reconfig.spec.ts.
 */
let adminTokenPromise: Promise<string> | undefined
function adminToken(request: APIRequestContext): Promise<string> {
  adminTokenPromise ??= apiLogin(request)
  return adminTokenPromise
}

// Logowanie RAZ na plik (wzór: s17); testy biegną sekwencyjnie (workers = 1).
const session = uiSession('s25-metadata-config')
test.use({ storageState: session.statePath })
test.setTimeout(120_000)
test.beforeAll(async ({ browser }) => {
  await session.login(browser)
})

type Envelope<T> = { code: number; message: string; data: T }

/** Rozwija kopertę RAGFlow (jak `helpers.ts`): HTTP 200 + `code 0`, inaczej `expect` rzuca. */
async function ok<T>(pending: Promise<APIResponse>, label: string): Promise<T> {
  const response = await pending
  const body = (await response.json()) as Envelope<T>
  expect(response.status(), `${label}: HTTP ${response.status()} — ${body.message}`).toBe(200)
  expect(body.code, `${label}: ${body.message}`).toBe(0)
  return body.data
}

/** Datasety do sprzątania po każdym teście (afterEach). */
const cleanupDatasets: string[] = []

test.afterEach(async ({ context, request }) => {
  const token = await adminToken(request)
  // Wariant EN zmienia język profilu — przywracamy PL, żeby kolejne testy widziały etykiety PL.
  await setProfileLanguage(request, token, 'pl')
  for (const id of cleanupDatasets.splice(0)) {
    await deleteDataset(request, token, id)
  }
  await session.save(context)
})

export type ListedDocument = {
  id: string
  name: string
  run: string
  meta_fields: Record<string, unknown>
  parser_config: Record<string, unknown>
}

/** Lista dokumentów datasetu (GET …/documents). */
async function listDocs(
  request: APIRequestContext,
  token: string,
  datasetId: string,
): Promise<ListedDocument[]> {
  const listed = await ok<{ docs: ListedDocument[] }>(
    request.get(`${API_URL}/api/v1/datasets/${datasetId}/documents`, {
      headers: { authorization: `Bearer ${token}` },
    }),
    'GET /api/v1/datasets/{id}/documents',
  )
  return listed.docs
}

/** Wgrywa plik przez API (multipart, wzór: s17) i zwraca id dokumentu. */
async function uploadDocument(
  request: APIRequestContext,
  token: string,
  datasetId: string,
  name: string,
  mime: string,
  bytes: Buffer,
): Promise<string> {
  const uploaded = await ok<{ id: string }[]>(
    request.post(`${API_URL}/api/v1/datasets/${datasetId}/documents`, {
      headers: { authorization: `Bearer ${token}` },
      multipart: { file: { name, mimeType: mime, buffer: bytes } },
    }),
    `POST /api/v1/datasets/{id}/documents (${name})`,
  )
  expect(uploaded, `upload ${name}: dokładnie jeden dokument`).toHaveLength(1)
  return uploaded[0]!.id
}

/** Poll (do 90 s) na `run = DONE` wskazanych dokumentów — bez własnego zlecenia parsowania. */
async function waitForParsed(
  request: APIRequestContext,
  token: string,
  datasetId: string,
  documentIds: string[],
): Promise<void> {
  const deadline = Date.now() + POLL_TIMEOUT_MS
  for (;;) {
    const docs = await listDocs(request, token, datasetId)
    const states = documentIds.map((id) => docs.find((doc) => doc.id === id)?.run ?? '')
    if (states.every((state) => state === 'DONE')) return
    if (states.some((state) => state === 'FAIL' || state === 'CANCEL')) {
      throw new Error(`parsowanie zakończone błędem: ${states.join(',')}`)
    }
    if (Date.now() > deadline) {
      throw new Error(
        `parsowanie niedokończone po ${POLL_TIMEOUT_MS / 1000} s: ${states.join(',')}`,
      )
    }
    await sleep(1_000)
  }
}

/**
 * Parsowanie plików wgranych przez API: POST …/documents/parse + poll na DONE. Dla plików wgranych
 * przez dialog UI NIE wołać — dialog sam parsuje („Parsuj po przesłaniu”), a drugie POST dla
 * dokumentu DONE jest przyjmowane (clear_existing) i parse #2 loguje „Auto metadata: 0 fields”.
 */
async function parseAndWait(
  request: APIRequestContext,
  token: string,
  datasetId: string,
  documentIds: string[],
): Promise<void> {
  const posted = await request.post(`${API_URL}/api/v1/datasets/${datasetId}/documents/parse`, {
    headers: { authorization: `Bearer ${token}` },
    data: { document_ids: documentIds },
  })
  const envelope = (await posted.json()) as Envelope<unknown>
  expect(posted.status(), `POST …/documents/parse: HTTP ${posted.status()}`).toBe(200)
  // Backend odrzuca podwójne zlecenie dla dokumentu już w kolejce (code 103, OperationNotAllowed).
  expect(
    envelope.code === 0 || envelope.code === 103,
    `POST …/documents/parse: ${envelope.message}`,
  ).toBe(true)
  await waitForParsed(request, token, datasetId, documentIds)
}

/** Zakładka „Konfiguracja” datasetu z nagłówkiem nazwy (sesja z `storageState`, wzór: s17). */
async function openConfig(page: Page, datasetId: string, name: string): Promise<void> {
  await page.goto(`/dataset/configuration/${datasetId}`)
  await expect(page.getByRole('heading', { name })).toBeVisible()
}

/**
 * Upload trzech plików przeciągnięciem (SC-01 krok 7): PDF + DOCX + fixture metadanych do
 * dialogu „Prześlij pliki”. `setInputFiles` jest zakazane (brief) — `DataTransfer` z bajtami
 * plików z `e2e/fixtures` (wzór: s15 + helpers/dnd.ts).
 */
async function uploadThreeFilesViaUi(page: Page): Promise<void> {
  await page.getByRole('tab', { name: 'Pliki' }).click()
  await page.getByTestId('files-add').click()
  const dialog = page.getByRole('dialog', { name: 'Prześlij pliki' })
  await expect(dialog).toBeVisible()
  await dropFile(
    page,
    page.getByTestId('upload-dropzone'),
    readFileSync(PDF_PATH),
    PDF_NAME,
    PDF_MIME,
  )
  await dropFile(
    page,
    page.getByTestId('upload-dropzone'),
    readFileSync(DOCX_PATH),
    DOCX_NAME,
    DOCX_MIME,
  )
  await dropFile(
    page,
    page.getByTestId('upload-dropzone'),
    readFileSync(FIXTURE_PATH),
    FIXTURE_NAME,
    FIXTURE_MIME,
  )
  // Dialog parsuje sam po przesłaniu — przełącznik musi być włączony (inaczej nic nie ruszy parsowania).
  await expect(page.getByTestId('upload-parse-toggle')).toBeChecked()
  await page.getByTestId('upload-start').click()
  await expect(dialog.getByText('Przesłano', { exact: true })).toHaveCount(3, { timeout: 60_000 })
  await page.getByTestId('upload-close').click()
  await expect(dialog).toBeHidden()
}

test('SC-E6-1b-01 kroki 1–8: sekcja „Metadane”, pola i chipy fixture, log „Auto metadata: 2 fields”', async ({
  page,
  request,
}) => {
  // Kroki 1–6 w UI + krok 7 (upload i parsowanie 3 plików) — zapas ponad domyślne 30 s (wzór: s17).
  test.setTimeout(300_000)
  const token = await adminToken(request)
  const name = `E2E S25 SC-01 ${uniq()}`
  const datasetId = await createDataset(request, token, name)
  cleanupDatasets.push(datasetId)

  await openConfig(page, datasetId, name)

  // Krok 1: sekcja „Metadane” pod „Metodą chunkowania”; przełącznik nieaktywny z podpowiedzią.
  const heading = page.getByRole('heading', { name: 'Metadane' })
  await expect(heading).toBeVisible()
  const order = await page.evaluate(() => {
    const chunk = [...document.querySelectorAll('label')].find((el) =>
      (el.textContent ?? '').trim().startsWith('Metoda chunkowania'),
    )
    const meta = [...document.querySelectorAll('h1, h2, h3, h4, h5, h6, [role="heading"]')].find(
      (el) => (el.textContent ?? '').trim() === 'Metadane',
    )
    if (chunk === undefined || meta === undefined) return 'missing'
    return (chunk.compareDocumentPosition(meta) & Node.DOCUMENT_POSITION_FOLLOWING) !== 0
      ? 'following'
      : 'preceding'
  })
  expect(order, 'sekcja „Metadane” pod „Metodą chunkowania”').toBe('following')
  const autoSwitch = page.getByRole('switch', { name: 'Auto-metadane' })
  await expect(autoSwitch).toBeDisabled()
  await expect(page.getByText('Dodaj co najmniej jedno pole')).toBeVisible()
  await expectNoLayoutDefects(
    page,
    'konfiguracja — sekcja „Metadane” przed dodaniem pól (SC-01 krok 1)',
  )

  // Krok 2: „+ Pole” → nowy wiersz z fokusem w „Klucz”; przełącznik staje się aktywny.
  await page.getByRole('button', { name: '+ Pole' }).click()
  const row1 = page.getByRole('group', { name: 'Pole 1' })
  await expect(row1).toBeVisible()
  const klucz1 = row1.getByLabel('Klucz')
  await expect(klucz1).toBeFocused()
  await klucz1.fill('rok')
  await row1.getByLabel('Opis').fill('Rok, którego dotyczą dane')
  await expect(autoSwitch).toBeEnabled()

  // Krok 3: drugie pole z trzema dozwolonymi wartościami (Enter po każdej).
  await page.getByRole('button', { name: '+ Pole' }).click()
  const row2 = page.getByRole('group', { name: 'Pole 2' })
  await expect(row2).toBeVisible()
  await row2.getByLabel('Klucz').fill('typ')
  await row2.getByLabel('Opis').fill('Rodzaj dokumentu')
  const values2 = row2.getByLabel('Dozwolona wartość')
  for (const value of ['raport', 'rocznik', 'ustawa']) {
    await values2.fill(value)
    await values2.press('Enter')
  }
  for (const value of ['raport', 'rocznik', 'ustawa']) {
    await expect(row2.locator(`[aria-label="Usuń wartość ${value}"]`)).toBeVisible()
  }
  await expect(values2).toHaveValue('')
  await expect(values2).toBeFocused()
  await expectNoLayoutDefects(page, 'konfiguracja — dwa pola metadanych z chipami (SC-01 krok 3)')

  // Krok 4: trzecie pole z powtórzonym kluczem → błąd przy polu, „Zapisz” nieaktywny.
  await page.getByRole('button', { name: '+ Pole' }).click()
  const row3 = page.getByRole('group', { name: 'Pole 3' })
  await expect(row3).toBeVisible()
  await row3.getByLabel('Klucz').fill('rok')
  await expect(row3.getByText('Klucz musi być unikalny')).toBeVisible()
  await expect(row3.getByLabel('Klucz')).toHaveAttribute('aria-invalid', 'true')
  await expect(page.getByRole('button', { name: 'Zapisz' })).toBeDisabled()

  // Krok 5: usuwa trzecie pole, włącza „Auto-metadane”, czyta podpowiedź ⓘ.
  await row3.getByRole('button', { name: 'Usuń pole' }).click()
  await expect(row3).toBeHidden()
  await autoSwitch.click()
  await expect(autoSwitch).toBeChecked()
  await page.getByRole('button', { name: 'Informacja o auto-metadanych' }).hover()
  await expect(page.getByRole('tooltip')).toContainText(
    'Działa przy następnym parsowaniu — istniejące pliki: „Parsuj ponownie”',
  )

  // Krok 6: „Zapisz” → sukces; po F5 pola i przełącznik zachowane dokładnie. Dataset nie ma
  // plików, więc dialog „Zastosować zmiany…” nie ma prawa się otworzyć (wzór: s17).
  await page.getByRole('button', { name: 'Zapisz' }).click()
  await expect(page.getByText('Zapisano')).toBeVisible()
  await expect(page.getByRole('dialog', { name: APPLY_TITLE })).toHaveCount(0)
  await page.reload()
  await expect(page.getByRole('heading', { name })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Metadane' })).toBeVisible()
  await expect(autoSwitch).toBeChecked()
  await expect(row1.getByLabel('Klucz')).toHaveValue('rok')
  await expect(row1.getByLabel('Opis')).toHaveValue('Rok, którego dotyczą dane')
  await expect(row2.getByLabel('Klucz')).toHaveValue('typ')
  await expect(row2.getByLabel('Opis')).toHaveValue('Rodzaj dokumentu')
  for (const value of ['raport', 'rocznik', 'ustawa']) {
    await expect(row2.locator(`[aria-label="Usuń wartość ${value}"]`)).toBeVisible()
  }

  // Krok 7: wgrywa (przeciąganiem) 3 pliki, czeka na „Sukces”; fixture ma chipy metadanych.
  await uploadThreeFilesViaUi(page)
  const docs = await listDocs(request, token, datasetId)
  const ids = [PDF_NAME, DOCX_NAME, FIXTURE_NAME].map(
    (docName) => docs.find((doc) => doc.name === docName)?.id ?? '',
  )
  expect(ids, 'trzy wgrane dokumenty na liście').not.toContain('')
  await waitForParsed(request, token, datasetId, ids)
  // Kolumna „Metadane” jest od xl (≥ 1536 px, decyzja TL 2026-10-13 — CONTRACT §4; przy 1280
  // metadane przez ⋮ i szufladę) — asercje kolumny i chipów biegną przy 1600 px (wzór: s25-metadata-list).
  await page.setViewportSize({ width: 1600, height: 900 })
  await page.goto(`/dataset/files/${datasetId}`)
  await expect(page.getByRole('heading', { name })).toBeVisible()
  await expect(page.getByRole('columnheader', { name: 'Metadane' })).toBeVisible()
  const fixtureRow = page.getByRole('row').filter({ hasText: FIXTURE_NAME })
  const pdfRow = page.getByRole('row').filter({ hasText: PDF_NAME })
  const docxRow = page.getByRole('row').filter({ hasText: DOCX_NAME })
  for (const [row, docId] of [
    [pdfRow, ids[0]],
    [docxRow, ids[1]],
    [fixtureRow, ids[2]],
  ] as const) {
    await expect(row.getByTestId(`status-cell-${docId}`)).toContainText('Sukces', {
      timeout: POLL_TIMEOUT_MS,
    })
  }
  await expect(fixtureRow.getByText('rok: 2023')).toBeVisible()
  await expect(fixtureRow.getByText('typ: raport')).toBeVisible()
  await expect(pdfRow.getByText('—', { exact: true })).toBeVisible()
  await expect(docxRow.getByText('—', { exact: true })).toBeVisible()
  await expectNoLayoutDefects(page, 'lista plików z chipami metadanych (SC-01 krok 7)')

  // Krok 8: log zadania fixture'a — wpis „Auto metadata: 2 fields” workera (K11 §10f)
  // pokazany w UI po polsku (V12-2 T3b: plural few — „2 pola”).
  await fixtureRow.getByTestId(`status-log-${ids[2]}`).click()
  const logDialog = page.getByRole('dialog', { name: `Log parsowania — ${FIXTURE_NAME}` })
  await expect(logDialog).toBeVisible()
  await expect(logDialog).toContainText('Metadane automatyczne: 2 pola')
  await expect(logDialog).not.toContainText('Auto metadata: 2 fields')
})

test.describe('SC-E6-1b-01 wariant: ciemny motyw (kroki 1–3, 7)', () => {
  test.use({ colorScheme: 'dark' })

  test('sekcja „Metadane” i chipy na liście w ciemnym motywie', async ({ page, request }) => {
    test.setTimeout(300_000)
    const token = await adminToken(request)
    const name = `E2E S25 SC-01 dark ${uniq()}`
    const datasetId = await createDataset(request, token, name)
    cleanupDatasets.push(datasetId)

    await openConfig(page, datasetId, name)

    // Kroki 1–3 w ciemnym motywie: pusta sekcja, „+ Pole”, pola i chipy dozwolonych wartości.
    await expect(page.getByRole('heading', { name: 'Metadane' })).toBeVisible()
    const autoSwitch = page.getByRole('switch', { name: 'Auto-metadane' })
    await expect(autoSwitch).toBeDisabled()
    await expect(page.getByText('Dodaj co najmniej jedno pole')).toBeVisible()
    await page.getByRole('button', { name: '+ Pole' }).click()
    const row1 = page.getByRole('group', { name: 'Pole 1' })
    await row1.getByLabel('Klucz').fill('rok')
    await row1.getByLabel('Opis').fill('Rok, którego dotyczą dane')
    await page.getByRole('button', { name: '+ Pole' }).click()
    const row2 = page.getByRole('group', { name: 'Pole 2' })
    await row2.getByLabel('Klucz').fill('typ')
    const values2 = row2.getByLabel('Dozwolona wartość')
    for (const value of ['raport', 'rocznik', 'ustawa']) {
      await values2.fill(value)
      await values2.press('Enter')
    }
    await expectNoLayoutDefects(
      page,
      'konfiguracja — sekcja „Metadane” w ciemnym motywie (kroki 1–3)',
    )

    // Zapis (akcja po kroku 3, żeby krok 7 miał włączone auto-metadane) i upload przeciąganiem.
    await autoSwitch.click()
    await page.getByRole('button', { name: 'Zapisz' }).click()
    await expect(page.getByText('Zapisano')).toBeVisible()
    await uploadThreeFilesViaUi(page)
    const docs = await listDocs(request, token, datasetId)
    const ids = [PDF_NAME, DOCX_NAME, FIXTURE_NAME].map(
      (docName) => docs.find((doc) => doc.name === docName)?.id ?? '',
    )
    expect(ids, 'trzy wgrane dokumenty na liście').not.toContain('')
    await waitForParsed(request, token, datasetId, ids)
    // Chipy są w kolumnie „Metadane” (od xl, ≥ 1536 px) — krok 7 przy 1600 px (jak wyżej).
    await page.setViewportSize({ width: 1600, height: 900 })
    await page.goto(`/dataset/files/${datasetId}`)
    await expect(page.getByRole('heading', { name })).toBeVisible()
    const fixtureRow = page.getByRole('row').filter({ hasText: FIXTURE_NAME })
    await expect(fixtureRow.getByTestId(`status-cell-${ids[2]}`)).toContainText('Sukces', {
      timeout: POLL_TIMEOUT_MS,
    })
    await expect(fixtureRow.getByText('rok: 2023')).toBeVisible()
    await expect(fixtureRow.getByText('typ: raport')).toBeVisible()
    await expectNoLayoutDefects(page, 'lista plików z chipami w ciemnym motywie (krok 7)')
  })
})

test('SC-E6-1b-01 wariant EN: etykiety sekcji i podpowiedzi po angielsku', async ({
  page,
  request,
}) => {
  const token = await adminToken(request)
  // Profil admina nadpisuje locale przeglądarki po zalogowaniu (wzór: s17); afterEach przywraca PL.
  await setProfileLanguage(request, token, 'en')
  const name = `E2E S25 SC-01 EN ${uniq()}`
  const datasetId = await createDataset(request, token, name)
  cleanupDatasets.push(datasetId)

  await openConfig(page, datasetId, name)

  // Etykiety sekcji (CONTRACT §4 EN min.): „Metadata”, „Auto-metadata”, „+ Field”, podpowiedź.
  await expect(page.getByRole('heading', { name: 'Metadata' })).toBeVisible()
  const autoSwitch = page.getByRole('switch', { name: 'Auto-metadata' })
  await expect(autoSwitch).toBeDisabled()
  await expect(page.getByText('Add at least one field')).toBeVisible()
  await expect(page.getByRole('button', { name: '+ Field' })).toBeVisible()

  // Pole w EN: nowy wiersz dostaje fokus w „Key” (etykiety wiersza pól i grup po EN nie są
  // wiążące w CONTRACT §4 — pokrywa je wariant PL); po dodaniu przełącznik aktywny.
  await page.getByRole('button', { name: '+ Field' }).click()
  const keyField = page.getByLabel('Key')
  await expect(keyField).toBeFocused()
  await keyField.fill('rok')
  await expect(autoSwitch).toBeEnabled()
  await expectNoLayoutDefects(page, 'konfiguracja — sekcja „Metadata” w EN')
})

test('SC-E6-1b-01 wariant długie dane: klucz 64, opis 300, 12 wartości — wielokropek i title', async ({
  page,
  request,
}) => {
  const token = await adminToken(request)
  const name = `E2E S25 SC-01 long ${uniq()}`
  const datasetId = await createDataset(request, token, name)
  cleanupDatasets.push(datasetId)

  await openConfig(page, datasetId, name)
  await expect(page.getByRole('heading', { name: 'Metadane' })).toBeVisible()

  await page.getByRole('button', { name: '+ Pole' }).click()
  const row1 = page.getByRole('group', { name: 'Pole 1' })
  await row1.getByLabel('Klucz').fill(LONG_KEY)
  await row1.getByLabel('Opis').fill(LONG_DESCRIPTION)
  const values1 = row1.getByLabel('Dozwolona wartość')
  for (const value of LONG_ENUM) {
    await values1.fill(value)
    await values1.press('Enter')
  }
  // 12 chipów; pola tekstowe trzymają pełne wartości (wpis widoczny/przewijalny w polu).
  await expect(row1.locator('[aria-label^="Usuń wartość "]')).toHaveCount(12)
  await expect(row1.getByLabel('Klucz')).toHaveValue(LONG_KEY)
  await expect(row1.getByLabel('Opis')).toHaveValue(LONG_DESCRIPTION)
  // Długa wartość: chip ma `title` z pełną treścią (wielokropek pilnuje strażnik układu —
  // ucięcie bez `text-overflow: ellipsis` to wada `clipped`).
  const titled = await page.evaluate((value) => {
    const chip = [...document.querySelectorAll('[title]')].find((el) =>
      (el.textContent ?? '').includes(value),
    )
    if (chip === undefined) return 'missing'
    return (chip.getAttribute('title') ?? '').includes(value) ? 'titled' : 'no-title'
  }, LONG_VALUE)
  expect(titled, 'chip długiej wartości ma title z pełną treścią').toBe('titled')
  // „Nic nie wychodzi poza kartę”: poziomy overflow strony = wada `overflow-page`.
  await expectNoLayoutDefects(page, 'karta konfiguracji z długimi danymi (SC-01 wariant)')
})

test('SC-E6-1b-01 wariant błąd API przy zapisie: komunikat i wpisane pola zostają', async ({
  page,
  request,
}) => {
  const token = await adminToken(request)
  const name = `E2E S25 SC-01 save-error ${uniq()}`
  const datasetId = await createDataset(request, token, name)
  cleanupDatasets.push(datasetId)

  await openConfig(page, datasetId, name)
  await expect(page.getByRole('heading', { name: 'Metadane' })).toBeVisible()
  await page.getByRole('button', { name: '+ Pole' }).click()
  const row1 = page.getByRole('group', { name: 'Pole 1' })
  await row1.getByLabel('Klucz').fill('rok')
  await row1.getByLabel('Opis').fill('Rok, którego dotyczą dane')
  const autoSwitch = page.getByRole('switch', { name: 'Auto-metadane' })
  await autoSwitch.click()

  // Awaria PUT `…/metadata/config`. Koperta HTTP 200 + `code ≠ 0` (wzór: s17-model-edit):
  // odpowiedź HTTP 500 logowałaby się jako błąd konsoli i wywaliła test strażnikiem z
  // `fixtures.ts`; UI widzi ten sam `ApiError`.
  await page.route(`**/api/v1/datasets/*/metadata/config`, async (route) => {
    if (route.request().method() === 'PUT') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ code: 500, message: 'E2E: symulowana awaria zapisu metadanych' }),
      })
      return
    }
    await route.continue()
  })
  await page.getByRole('button', { name: 'Zapisz' }).click()
  // Komunikat przy polu (08 §7.14 U5, SC-E67-06), nie alert karty.
  await expect(row1.getByText('symulowana awaria zapisu metadanych')).toBeVisible()
  await expect(page.getByRole('alert')).toHaveCount(0)
  // Wpisane pola zostają (stan formularza nietknięty, brak „Zapisano”).
  await expect(page.getByText('Zapisano')).toHaveCount(0)
  await expect(row1.getByLabel('Klucz')).toHaveValue('rok')
  await expect(row1.getByLabel('Opis')).toHaveValue('Rok, którego dotyczą dane')
  await expect(autoSwitch).toBeChecked()
  // Konfiguracja na backendzie bez zmian — PUT nie doszedł do skutku.
  const config = await ok<{ metadata: unknown[] }>(
    request.get(`${API_URL}/api/v1/datasets/${datasetId}/metadata/config`, {
      headers: { authorization: `Bearer ${token}` },
    }),
    'GET …/metadata/config',
  )
  expect(config.metadata, 'lista pól na backendzie pusta po nieudanym zapisie').toHaveLength(0)
})

test('SC-E6-1b-01 wariant klawiatura: Tab przez pola, Enter dodaje chip, Esc nie kasuje wiersza', async ({
  page,
  request,
}) => {
  const token = await adminToken(request)
  const name = `E2E S25 SC-01 kbd ${uniq()}`
  const datasetId = await createDataset(request, token, name)
  cleanupDatasets.push(datasetId)

  await openConfig(page, datasetId, name)
  await expect(page.getByRole('heading', { name: 'Metadane' })).toBeVisible()

  await page.getByRole('button', { name: '+ Pole' }).click()
  const row1 = page.getByRole('group', { name: 'Pole 1' })
  await row1.getByLabel('Klucz').fill('rok')
  await page.getByRole('button', { name: '+ Pole' }).click()
  const row2 = page.getByRole('group', { name: 'Pole 2' })
  await row2.getByLabel('Klucz').fill('typ')

  // Tab przechodzi przez pola wiersza: „Klucz” → „Opis”.
  await row2.getByLabel('Klucz').focus()
  await page.keyboard.press('Tab')
  await expect(row2.getByLabel('Opis')).toBeFocused()

  // Enter w polu wartości dodaje chip, czyści pole i zostawia fokus.
  const values2 = row2.getByLabel('Dozwolona wartość')
  await values2.fill('raport')
  await values2.press('Enter')
  await expect(row2.locator('[aria-label="Usuń wartość raport"]')).toBeVisible()
  await expect(values2).toHaveValue('')
  await expect(values2).toBeFocused()

  // Esc w polu wartości nie usuwa wiersza.
  await page.keyboard.press('Escape')
  await expect(row2).toBeVisible()
  await expect(row2.locator('[aria-label="Usuń wartość raport"]')).toBeVisible()
})

test('SC-E6-1b-02 kroki 1–5: dialog R-CFG-01, „Parsuj ponownie istniejące”, chip bez odświeżania, chip trwa', async ({
  page,
  request,
}) => {
  test.setTimeout(300_000)
  const token = await adminToken(request)
  const name = `E2E S25 SC-02 ${uniq()}`
  const datasetId = await createDataset(request, token, name)
  cleanupDatasets.push(datasetId)
  // Krok 1 (dane): 1 plik (fixture) sparsowany BEZ auto-metadanych — konfiguracji nie ma.
  const fixtureId = await uploadDocument(
    request,
    token,
    datasetId,
    FIXTURE_NAME,
    FIXTURE_MIME,
    readFileSync(FIXTURE_PATH),
  )
  await parseAndWait(request, token, datasetId, [fixtureId])

  // Kolumna „Metadane” od xl (≥ 1536 px, decyzja TL 2026-10-13 — CONTRACT §4): krok 1 i chipy
  // kroków 4–5 przy 1600 px (wzór: s25-metadata-list).
  await page.setViewportSize({ width: 1600, height: 900 })
  await page.goto(`/dataset/files/${datasetId}`)
  await expect(page.getByRole('heading', { name })).toBeVisible()
  const fixtureRow = page.getByRole('row').filter({ hasText: FIXTURE_NAME })
  await expect(fixtureRow).toBeVisible()
  await expect(fixtureRow.getByTestId(`status-cell-${fixtureId}`)).toContainText('Sukces')
  // Krok 1: kolumna „Metadane” jest, a wiersz fixture'a pusty („—”).
  await expect(page.getByRole('columnheader', { name: 'Metadane' })).toBeVisible()
  await expect(fixtureRow.getByText('—', { exact: true })).toBeVisible()

  // Krok 2: konfiguracja — pole `rok`, włączenie „Auto-metadane”, „Zapisz” → dialog R-CFG-01.
  await page.getByRole('tab', { name: 'Konfiguracja' }).click()
  await page.getByRole('button', { name: '+ Pole' }).click()
  const row1 = page.getByRole('group', { name: 'Pole 1' })
  await row1.getByLabel('Klucz').fill('rok')
  await page.getByRole('switch', { name: 'Auto-metadane' }).click()
  await page.getByRole('button', { name: 'Zapisz' }).click()
  const dialog = page.getByRole('dialog', { name: APPLY_TITLE })
  await expect(dialog).toBeVisible()
  // Wiersz „Zmieniono: …” wymienia oba zmienione aspekty (CONTRACT §4).
  await expect(dialog).toContainText('Auto-metadane')
  await expect(dialog).toContainText('Pola metadanych')
  // Teksty przycisków z istniejącego `ApplyToFilesDialog` (`locales/pl/datasets.json`):
  // scenariusz mówi „Parsuj ponownie istniejące” — w kodzie jest „Zastosuj i parsuj ponownie (N)”.
  await expect(dialog.getByRole('button', { name: 'Tylko nowe pliki' })).toBeVisible()
  await expect(dialog.getByRole('button', { name: 'Zastosuj i parsuj ponownie (1)' })).toBeVisible()

  // Krok 3 (korekta TL 2026-10-13, SCENARIOS.md): „Parsuj ponownie istniejące” — dokument
  // dziedziczy `parser_config` tylko przy uploadzie, więc ta opcja dialogu R-CFG-01 jest jedyną
  // drogą przeniesienia auto-metadanych na istniejący plik (PATCH parser_config + POST chunks).
  await dialog.getByRole('button', { name: 'Zastosuj i parsuj ponownie (1)' }).click()
  await expect(dialog).toBeHidden()
  // Po udanym apply dialog pokazuje TOAST o tym samym tekście co inline-alert zapisu
  // (`show(t('datasets.config.saved'))`) — `.first()` akceptuje oba.
  await expect(page.getByText('Zapisano').first()).toBeVisible()
  // Transfer konfiguracji na dokument — parser_config dokumentu niesie włączony przełącznik
  // i listę pól (przyczyna poprawności kroku 4).
  const applied = (await listDocs(request, token, datasetId)).find((doc) => doc.id === fixtureId)
  expect(
    applied?.parser_config?.enable_metadata,
    'enable_metadata na dokumencie po transferze',
  ).toBe(true)
  // Kroki 2–3 biegną na zakładce „Konfiguracja” (lista plików odmontowana) — jak w kroku 5,
  // przed asercjami wiersza wracamy na „Pliki”.
  await page.getByRole('tab', { name: 'Pliki' }).click()
  // Plik ponownie parsowany — „Sukces” wraca (komórka przechodzi przez „Parsowanie…”).
  await expect(fixtureRow.getByTestId(`status-cell-${fixtureId}`)).toContainText('Sukces', {
    timeout: POLL_TIMEOUT_MS,
  })

  // Krok 4: chip `rok: 2023` w kolumnie „Metadane” ≤ 5 s po „Sukces”, bez ręcznego odświeżania
  // (lista odpytuje co 3 s; budżet testowy szerszy — POLL_TIMEOUT_MS).
  await expect(fixtureRow.getByText('rok: 2023')).toBeVisible({ timeout: POLL_TIMEOUT_MS })

  // Krok 5: usunięcie pola `rok` i zapis (bez ponownego parsowania) — chip zostaje.
  await page.getByRole('tab', { name: 'Konfiguracja' }).click()
  await page
    .getByRole('group', { name: 'Pole 1' })
    .getByRole('button', { name: 'Usuń pole' })
    .click()
  await page.getByRole('button', { name: 'Zapisz' }).click()
  const dialog2 = page.getByRole('dialog', { name: APPLY_TITLE })
  await expect(dialog2).toBeVisible()
  await dialog2.getByRole('button', { name: 'Tylko nowe pliki' }).click()
  await expect(dialog2).toBeHidden()
  await page.getByRole('tab', { name: 'Pliki' }).click()
  await expect(fixtureRow.getByText('rok: 2023')).toBeVisible()
  const after = (await listDocs(request, token, datasetId)).find((doc) => doc.id === fixtureId)
  expect(after?.meta_fields, 'meta_fields pliku po usunięciu pola datasetu').toEqual({
    rok: '2023',
  })
})

test('SC-E6-1b-02 wariant „Tylko nowe pliki”: plik bez chipa, status „Sukces” bez zmian', async ({
  page,
  request,
}) => {
  const token = await adminToken(request)
  const name = `E2E S25 SC-02 newonly ${uniq()}`
  const datasetId = await createDataset(request, token, name)
  cleanupDatasets.push(datasetId)
  const fixtureId = await uploadDocument(
    request,
    token,
    datasetId,
    FIXTURE_NAME,
    FIXTURE_MIME,
    readFileSync(FIXTURE_PATH),
  )
  await parseAndWait(request, token, datasetId, [fixtureId])

  // Kolumna „Metadane” od xl (≥ 1536 px) — ten sam viewport co wariant główny.
  await page.setViewportSize({ width: 1600, height: 900 })
  await page.goto(`/dataset/files/${datasetId}`)
  await expect(page.getByRole('heading', { name })).toBeVisible()
  const fixtureRow = page.getByRole('row').filter({ hasText: FIXTURE_NAME })
  await expect(fixtureRow.getByTestId(`status-cell-${fixtureId}`)).toContainText('Sukces')

  await page.getByRole('tab', { name: 'Konfiguracja' }).click()
  await page.getByRole('button', { name: '+ Pole' }).click()
  await page.getByRole('group', { name: 'Pole 1' }).getByLabel('Klucz').fill('rok')
  await page.getByRole('switch', { name: 'Auto-metadane' }).click()
  await page.getByRole('button', { name: 'Zapisz' }).click()
  const dialog = page.getByRole('dialog', { name: APPLY_TITLE })
  await expect(dialog).toBeVisible()
  await dialog.getByRole('button', { name: 'Tylko nowe pliki' }).click()
  await expect(dialog).toBeHidden()
  await expect(page.getByText('Zapisano')).toBeVisible()

  // Istniejący plik NIE dostaje metadanych (dziedziczy parser_config tylko przy uploadzie):
  // kolumna pusta („—”), status „Sukces” bez zmian, meta_fields puste też w API.
  await page.getByRole('tab', { name: 'Pliki' }).click()
  await expect(fixtureRow.getByText('—', { exact: true })).toBeVisible()
  await expect(fixtureRow.getByTestId(`status-cell-${fixtureId}`)).toContainText('Sukces')
  const docs = await listDocs(request, token, datasetId)
  const saved = docs.find((doc) => doc.id === fixtureId)
  expect(saved?.meta_fields, 'meta_fields po „Tylko nowe pliki”').toEqual({})
  expect(
    saved?.parser_config?.enable_metadata,
    'enable_metadata dokumentu nietknięte',
  ).toBeUndefined()
})
