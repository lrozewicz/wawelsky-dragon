// Scenariusze SC-E6-1b-03 i SC-E6-1b-04 (SCENARIOS.md WP E6-1b, brief T1a): lista dokumentów —
// szuflada metadanych (⋮ → „Metadane”, edycja pól, „Zapisz”, błąd zapisu) oraz filtr metadanych
// (przycisk „Filtr metadanych”, kreator warunków, chip „Metadane: N warunków”, pusty wynik
// filtra). Na bazie (bez implementacji T5a/T5b) testy są CZERWONE z właściwej przyczyny: brak
// pozycji „Metadane” w menu wiersza, brak kolumny „Metadane”, brak przycisku „Filtr metadanych”
// — setup (logowanie, dataset, upload, auto-metadane przez API, parsowanie) dochodzi do punktu,
// w którym brakuje UI.
// Wzorce: s17-dataset-reconfig.spec.ts (sesja `uiSession`, memoizacja tokenu, sprzątanie,
// poll parsowania po API), expectNoLayoutDefects na każdym ekranie scenariusza.
// Etykiety i teksty — dosłownie CONTRACT WP E6-1b §4; odchyłka §6 (SC-04 krok 4): dokument bez
// klucza nie pasuje do żadnego operatora, więc `not empty` → 2 dokumenty, `empty` → pusty wynik.
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import type { APIRequestContext, APIResponse, Page } from '@playwright/test'

import { expect, test } from './fixtures'
import { POLL_TIMEOUT_MS, apiLogin, createDataset } from './helpers'
import { deleteDataset } from './helpers/files'
import { expectNoLayoutDefects } from './helpers/layout'
import { uiSession } from './helpers/session'

const API_URL = process.env.WD_E2E_API_URL ?? ''

const FIXTURE_NAME = 'metadata-rok-typ.txt'
const PDF_NAME = 'sample.pdf'
const DOCX_NAME = 'sample.docx'
const PDF_MIME = 'application/pdf'
const DOCX_MIME = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
const FIXTURE_MIME = 'text/plain'
const PDF_PATH = fileURLToPath(new URL('./fixtures/sample.pdf', import.meta.url))
const DOCX_PATH = fileURLToPath(new URL('./fixtures/sample.docx', import.meta.url))
const FIXTURE_PATH = fileURLToPath(new URL('./fixtures/metadata-rok-typ.txt', import.meta.url))

// Wartość z SC-03 krok 4: 200 znaków — chip w kolumnie z wielokropkiem i `title`.
const LONG_VALUE = 'x'.repeat(200)

// Pola auto-metadanych datasetu (jak w SC-E6-1b-01; kształt PUT — CONTRACT §1).
type FieldDef = { key: string; type: 'string'; description: string | null; enum: string[] | null }
const FIELDS: FieldDef[] = [
  { key: 'rok', type: 'string', description: 'Rok, którego dotyczą dane', enum: null },
  {
    key: 'typ',
    type: 'string',
    description: 'Rodzaj dokumentu',
    enum: ['raport', 'rocznik', 'ustawa'],
  },
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

// Logowanie RAZ na plik; testy biegną sekwencyjnie (workers = 1).
const session = uiSession('s25-metadata-list')
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

/**
 * Konfiguracja auto-metadanych przez API (CONTRACT §1): PUT `…/metadata/config` (lista pól)
 * i zwykły PUT `/datasets/{id}` z `parser_config.enable_metadata` (backend scala częściowy
 * `parser_config`, więc `metadata` z konfiguracji przetrwa).
 */
async function enableAutoMetadata(
  request: APIRequestContext,
  token: string,
  datasetId: string,
): Promise<void> {
  const headers = { authorization: `Bearer ${token}` }
  await ok<unknown>(
    request.put(`${API_URL}/api/v1/datasets/${datasetId}/metadata/config`, {
      headers,
      data: { metadata: FIELDS },
    }),
    'PUT /api/v1/datasets/{id}/metadata/config',
  )
  await ok<unknown>(
    request.put(`${API_URL}/api/v1/datasets/${datasetId}`, {
      headers,
      data: { parser_config: { enable_metadata: true } },
    }),
    'PUT /api/v1/datasets/{id} (enable_metadata)',
  )
}

/** Zapis `meta_fields` dokumentu przez API (CONTRACT §1: cała słownikowa nadpisanka). */
async function patchDocMeta(
  request: APIRequestContext,
  token: string,
  datasetId: string,
  documentId: string,
  metaFields: Record<string, unknown>,
): Promise<void> {
  await ok<unknown>(
    request.patch(`${API_URL}/api/v1/datasets/${datasetId}/documents/${documentId}`, {
      headers: { authorization: `Bearer ${token}` },
      data: { meta_fields: metaFields },
    }),
    `PATCH /datasets/{id}/documents/{id} (${documentId})`,
  )
}

/** Parsowanie dokumentów (POST …/documents/parse) i poll (do 90 s) na `run = DONE`. */
async function parseAndWait(
  request: APIRequestContext,
  token: string,
  datasetId: string,
  documentIds: string[],
): Promise<void> {
  const headers = { authorization: `Bearer ${token}` }
  await ok<unknown>(
    request.post(`${API_URL}/api/v1/datasets/${datasetId}/documents/parse`, {
      headers,
      data: { document_ids: documentIds },
    }),
    'POST /api/v1/datasets/{id}/documents/parse',
  )
  const deadline = Date.now() + POLL_TIMEOUT_MS
  for (;;) {
    const listed = await ok<{ docs: ListedDocument[] }>(
      request.get(`${API_URL}/api/v1/datasets/${datasetId}/documents`, {
        headers,
      }),
      'GET /api/v1/datasets/{id}/documents',
    )
    const states = documentIds.map((id) => listed.docs.find((doc) => doc.id === id)?.run ?? '')
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
 * Dataset jak w SC-E6-1b-01 (fixture + PDF + DOCX, auto-metadane włączone PRZED uploadem —
 * dokument dziedziczy `parser_config` przy uploadzie, CONTRACT §1). Fixture po parsowaniu ma
 * `rok: 2023` i `typ: raport` (fake-llm, K10 „Poprawka 2026-10-11b”); PDF/DOCX bez dopasowań.
 */
async function seedMetadataDataset(
  request: APIRequestContext,
  token: string,
  label: string,
): Promise<{ datasetId: string; name: string; fixtureId: string; pdfId: string; docxId: string }> {
  const name = `E2E S25 ${label} ${uniq()}`
  const datasetId = await createDataset(request, token, name)
  cleanupDatasets.push(datasetId)
  await enableAutoMetadata(request, token, datasetId)
  const fixtureId = await uploadDocument(
    request,
    token,
    datasetId,
    FIXTURE_NAME,
    FIXTURE_MIME,
    readFileSync(FIXTURE_PATH),
  )
  const pdfId = await uploadDocument(
    request,
    token,
    datasetId,
    PDF_NAME,
    PDF_MIME,
    readFileSync(PDF_PATH),
  )
  const docxId = await uploadDocument(
    request,
    token,
    datasetId,
    DOCX_NAME,
    DOCX_MIME,
    readFileSync(DOCX_PATH),
  )
  await parseAndWait(request, token, datasetId, [fixtureId, pdfId, docxId])
  return { datasetId, name, fixtureId, pdfId, docxId }
}

/** Lista plików datasetu z nagłówkiem nazwy (sesja z `storageState`, wzór: s15). */
async function openFiles(page: Page, datasetId: string, name: string): Promise<void> {
  await page.goto(`/dataset/files/${datasetId}`)
  await expect(page.getByRole('heading', { name })).toBeVisible()
}

// Kolumna „Metadane” jest od ≥ 1536 px (kontrakt §4 — TL 2026-10-13); testy czytające chipy
// kolumny biegną na 1600 px. Wariant 390 px poniżej nadpisuje viewport.
test.describe('SC-E6-1b-03 przy 1600 px (kolumna Metadane od xl)', () => {
  test.use({ viewport: { width: 1600, height: 900 } })

  test('SC-E6-1b-03 kroki 1–6: szuflada metadanych — dodanie pól, zapis, wielokropek, Anuluj/Esc, błąd', async ({
    page,
    request,
  }) => {
    test.setTimeout(300_000)
    const token = await adminToken(request)
    const { datasetId, name, pdfId } = await seedMetadataDataset(request, token, 'SC-03')

    await openFiles(page, datasetId, name)
    // Defekt QA E6-1b-1 (D2): przy 1600 px kolumna „Nazwa” kurczyła się do ~49 px, bo Container
    // maxWidth=lg zaciskał treść do ~1150 px przy 893 px kolumn stałych. Poprawka: dla zakładki
    // „Pliki” kontener rośnie do xl przy ≥ 1536 px; poniżej 1536 zachowanie bez zmian (s18/s21/s24).
    const nameHeader = page.getByRole('columnheader', { name: 'Nazwa' })
    await expect(nameHeader).toBeVisible()
    const nameHeaderBox = await nameHeader.boundingBox()
    expect(
      nameHeaderBox?.width ?? 0,
      'kolumna „Nazwa” ma ≥ 220 px przy 1600 px',
    ).toBeGreaterThanOrEqual(220)
    const pdfRow = page.getByRole('row').filter({ hasText: PDF_NAME })
    await expect(pdfRow).toBeVisible()
    // Pusta komórka „Metadane” = „—” (kontrakt §4; MINOR T5a: brak asercji).
    await expect(pdfRow.getByText('—')).toBeVisible()

    // Krok 1: ⋮ wiersza → „Metadane” → szuflada z prawej, tytuł = nazwa pliku, stan pusty.
    // Limity 10 s na klikach brakującego na bazie UI (przycisk ⋮ i pozycja menu): bez nich akcja
    // czeka do timeoutu TESTU (300 s), co czyni czerwień powolną. Uwaga: przy 390 px responsywny
    // ⋮ ISTNIEJE (pozycje zmiany nazwy/pobrania/usunięcia), więc czerwień wariantu pada dopiero
    // na brakującej pozycji „Metadane” (bieg T1a 2026-10-13).
    await pdfRow.getByTestId('row-actions-menu').click({ timeout: 10_000 })
    await page.getByRole('menuitem', { name: 'Metadane' }).click({ timeout: 10_000 })
    const drawer = page.getByRole('dialog', { name: PDF_NAME })
    await expect(drawer).toBeVisible()
    await expect(drawer.getByText('Brak metadanych — dodaj pierwsze pole')).toBeVisible()
    await expect(drawer.getByRole('button', { name: '+ Pole' })).toBeVisible()
    await expectNoLayoutDefects(page, 'szuflada metadanych — stan pusty (SC-03 krok 1)')

    // Krok 2: dwa pola przez „+ Pole”; „Zapisz” aktywny.
    await drawer.getByRole('button', { name: '+ Pole' }).click()
    await drawer.getByLabel('Klucz').nth(0).fill('typ')
    await drawer.getByLabel('Wartość').nth(0).fill('raport')
    await drawer.getByRole('button', { name: '+ Pole' }).click()
    await drawer.getByLabel('Klucz').nth(1).fill('region')
    await drawer.getByLabel('Wartość').nth(1).fill('mazowieckie')
    await expect(drawer.getByRole('button', { name: 'Zapisz' })).toBeEnabled()

    // Krok 3: „Zapisz” → szuflada się zamyka, fokus wraca na ⋮ wiersza, toast „Zapisano metadane”;
    // w kolumnie „Metadane” chipy obu pól.
    await drawer.getByRole('button', { name: 'Zapisz' }).click()
    await expect(drawer).toBeHidden()
    await expect(page.getByText('Zapisano metadane')).toBeVisible()
    await expect(pdfRow.getByTestId('row-actions-menu')).toBeFocused()
    await expect(pdfRow.getByText('typ: raport')).toBeVisible()
    await expect(pdfRow.getByText('region: mazowieckie')).toBeVisible()

    // Krok 4: wartość 200 znaków — w kolumnie chip z wielokropkiem i `title` z pełną wartością
    // (wielokropek pilnuje strażnik układu; ucięcie bez `text-overflow: ellipsis` to wada).
    await pdfRow.getByTestId('row-actions-menu').click({ timeout: 10_000 })
    await page.getByRole('menuitem', { name: 'Metadane' }).click({ timeout: 10_000 })
    await expect(drawer).toBeVisible()
    await drawer.getByLabel('Wartość').nth(1).fill(LONG_VALUE)
    await drawer.getByRole('button', { name: 'Zapisz' }).click()
    await expect(drawer).toBeHidden()
    const regionChip = pdfRow.getByText(/^region: /)
    await expect(regionChip).toBeVisible()
    const chipTitle = await regionChip.getAttribute('title')
    expect(chipTitle ?? '', 'title chipa z pełną wartością (200 znaków)').toContain(LONG_VALUE)
    await expectNoLayoutDefects(page, 'kolumna „Metadane” z długim chipem (SC-03 krok 4)')

    // Krok 5: porzucenie zmian — Esc i „Anuluj”; od SC-V12-07 zmiana pyta „Odrzucić zmiany?”,
    // „Odrzuć” porzuca ją i zamyka szufladę. Ponowne otwarcie pokazuje stan zapisany.
    await pdfRow.getByTestId('row-actions-menu').click({ timeout: 10_000 })
    await page.getByRole('menuitem', { name: 'Metadane' }).click({ timeout: 10_000 })
    await expect(drawer).toBeVisible()
    await drawer.getByLabel('Wartość').nth(0).fill('inny')
    await page.keyboard.press('Escape')
    const discard = page.getByRole('dialog', { name: 'Odrzucić zmiany?' })
    await expect(discard).toBeVisible()
    await discard.getByRole('button', { name: 'Odrzuć' }).click()
    await expect(drawer).toBeHidden()
    await pdfRow.getByTestId('row-actions-menu').click({ timeout: 10_000 })
    await page.getByRole('menuitem', { name: 'Metadane' }).click({ timeout: 10_000 })
    await expect(drawer.getByLabel('Wartość').nth(0)).toHaveValue('raport')
    await drawer.getByLabel('Wartość').nth(1).fill('krótkie')
    await drawer.getByRole('button', { name: 'Anuluj' }).click()
    await expect(discard).toBeVisible()
    await discard.getByRole('button', { name: 'Odrzuć' }).click()
    await expect(drawer).toBeHidden()
    await pdfRow.getByTestId('row-actions-menu').click({ timeout: 10_000 })
    await page.getByRole('menuitem', { name: 'Metadane' }).click({ timeout: 10_000 })
    await expect(drawer.getByLabel('Wartość').nth(1)).toHaveValue(LONG_VALUE)
    // Zamknięcie bez zmian: Esc zamyka od razu, bez dialogu (SC-V12-07 krok 3).
    await page.keyboard.press('Escape')
    await expect(drawer).toBeHidden()
    await expect(discard).toBeHidden()

    // Krok 6: awaria zapisu → komunikat w szufladzie, wpisane wartości zostają. Koperta
    // HTTP 200 + `code ≠ 0` (wzór: s17-model-edit) — HTTP 500 logowałby się jako błąd konsoli
    // i wywalił test strażnikiem z `fixtures.ts`; UI widzi ten sam `ApiError`.
    await page.route(`**/api/v1/datasets/*/documents/${pdfId}`, async (route) => {
      if (route.request().method() === 'PATCH') {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ code: 500, message: 'E2E: symulowana awaria zapisu metadanych' }),
        })
        return
      }
      await route.continue()
    })
    await pdfRow.getByTestId('row-actions-menu').click({ timeout: 10_000 })
    await page.getByRole('menuitem', { name: 'Metadane' }).click({ timeout: 10_000 })
    await expect(drawer).toBeVisible()
    await drawer.getByLabel('Wartość').nth(0).fill('inna wartość')
    await drawer.getByRole('button', { name: 'Zapisz' }).click()
    // T3b (wp/V12-2, 771f0832): szuflada pokazuje komunikat serwera z koperty (wg INVENTORY);
    // tekst bez pasującego szablonu wraca dosłownie — generyk „Nie udało się zapisać
    // metadanych” zostaje tylko dla błędu transportu (korekta asercji po zmianie bazowej).
    await expect(drawer.getByText('E2E: symulowana awaria zapisu metadanych')).toBeVisible()
    await expect(drawer.getByLabel('Wartość').nth(0)).toHaveValue('inna wartość')
    await expect(drawer).toBeVisible()
  })

  test('SC-E6-1b-03 wariant: dokument z 3 polami → 2 chipy i „+1”', async ({ page, request }) => {
    test.setTimeout(300_000)
    const token = await adminToken(request)
    const { datasetId, name, fixtureId } = await seedMetadataDataset(request, token, 'SC-03 plusN')
    // Trzecie pole (region) przez API — scenariusz mierzy zachowanie kolumny przy > 2 polach.
    await patchDocMeta(request, token, datasetId, fixtureId, {
      rok: '2023',
      typ: 'raport',
      region: 'mazowieckie',
    })

    await openFiles(page, datasetId, name)
    await expect(page.getByRole('columnheader', { name: 'Metadane' })).toBeVisible()
    const fixtureRow = page.getByRole('row').filter({ hasText: FIXTURE_NAME })
    await expect(fixtureRow).toBeVisible()
    await expect(fixtureRow.getByText('rok: 2023')).toBeVisible()
    await expect(fixtureRow.getByText('typ: raport')).toBeVisible()
    await expect(fixtureRow.getByText('+1')).toBeVisible()
    // Trzeci chip nie jest widoczny — jest w `title`/szufladzie, nie w kolumnie.
    await expect(fixtureRow.getByText('region: mazowieckie')).toHaveCount(0)
    await expectNoLayoutDefects(page, 'kolumna „Metadane” z chipem „+1” (SC-03 wariant)')
  })
})

test.describe('SC-E6-1b-03 wariant 390 px: kolumna ukryta, szuflada na pełną szerokość', () => {
  test.use({ viewport: { width: 390, height: 844 } })

  test('dostęp przez ⋮, szuflada wypełnia okno, zapis działa', async ({ page, request }) => {
    test.setTimeout(300_000)
    const token = await adminToken(request)
    const { datasetId, name, pdfId } = await seedMetadataDataset(request, token, 'SC-03 390')

    await openFiles(page, datasetId, name)
    // Poniżej 1536 px kolumny „Metadane” nie ma — dostęp tylko przez ⋮ → „Metadane”.
    await expect(page.getByRole('columnheader', { name: 'Metadane' })).toBeHidden()
    const pdfRow = page.getByRole('row').filter({ hasText: PDF_NAME })
    await expect(pdfRow).toBeVisible()
    await pdfRow.getByTestId('row-actions-menu').click({ timeout: 10_000 })
    await page.getByRole('menuitem', { name: 'Metadane' }).click({ timeout: 10_000 })
    const drawer = page.getByRole('dialog', { name: PDF_NAME })
    await expect(drawer).toBeVisible()
    const box = await drawer.boundingBox()
    expect(box?.width ?? 0, 'szuflada na pełną szerokość okna 390 px').toBeGreaterThanOrEqual(385)
    await expectNoLayoutDefects(page, 'szuflada metadanych przy 390 px')

    await drawer.getByRole('button', { name: '+ Pole' }).click()
    await drawer.getByLabel('Klucz').nth(0).fill('typ')
    await drawer.getByLabel('Wartość').nth(0).fill('raport')
    await drawer.getByRole('button', { name: 'Zapisz' }).click()
    await expect(drawer).toBeHidden()
    await expect(pdfRow.getByTestId('row-actions-menu')).toBeFocused()
    await expectNoLayoutDefects(page, 'lista plików przy 390 px po zapisie szuflady')
    // Stan zapisany trafił do dokumentu (PDF dostał typ=raport).
    const listed = await ok<{ docs: ListedDocument[] }>(
      request.get(`${API_URL}/api/v1/datasets/${datasetId}/documents`, {
        headers: { authorization: `Bearer ${token}` },
      }),
      'GET /api/v1/datasets/{id}/documents',
    )
    const pdf = listed.docs.find((doc) => doc.id === pdfId)
    expect(pdf?.meta_fields, 'meta_fields PDF po zapisie szuflady przy 390 px').toEqual({
      typ: 'raport',
    })
  })
})

test('SC-E6-1b-04 kroki 1–6: filtr metadanych — warunki, not empty/empty (odchyłka §6), czyszczenie', async ({
  page,
  request,
}) => {
  test.setTimeout(300_000)
  const token = await adminToken(request)
  const { datasetId, name, pdfId } = await seedMetadataDataset(request, token, 'SC-04')
  // PDF z metadanymi przez API (stan z SC-03): typ=raport, region=mazowieckie; DOCX bez metadanych.
  await patchDocMeta(request, token, datasetId, pdfId, { typ: 'raport', region: 'mazowieckie' })

  await openFiles(page, datasetId, name)
  const fixtureRow = page.getByRole('row').filter({ hasText: FIXTURE_NAME })
  const pdfRow = page.getByRole('row').filter({ hasText: PDF_NAME })
  const docxRow = page.getByRole('row').filter({ hasText: DOCX_NAME })
  await expect(fixtureRow).toBeVisible()
  await expect(pdfRow).toBeVisible()
  await expect(docxRow).toBeVisible()

  // Krok 1: „Filtr metadanych” → kreator warunków; klucze w selekcie z dokumentów datasetu.
  await page.getByRole('button', { name: 'Filtr metadanych' }).click({ timeout: 10_000 })
  const warunek1 = page.getByRole('group', { name: 'Warunek 1' })
  await expect(warunek1).toBeVisible()
  await warunek1.getByRole('combobox', { name: 'Klucz' }).click()
  await expect(page.getByRole('option', { name: 'rok', exact: true })).toBeVisible()
  await expect(page.getByRole('option', { name: 'typ', exact: true })).toBeVisible()
  await expect(page.getByRole('option', { name: 'region', exact: true })).toBeVisible()
  await page.getByRole('option', { name: 'typ', exact: true }).click()
  await expect(page.getByRole('combobox', { name: 'Logika warunków' })).toContainText('wszystkie')
  await expectNoLayoutDefects(page, 'kreator filtra metadanych (SC-04 krok 1)')

  // Krok 2: `typ = raport`, „Zastosuj” → 2 dokumenty (fixture, PDF); chip nad tabelą.
  await warunek1.getByRole('combobox', { name: 'Operator' }).click()
  await page.getByRole('option', { name: '=', exact: true }).click()
  await warunek1.getByRole('combobox', { name: 'Wartość' }).click()
  await page.getByRole('option', { name: 'raport' }).click()
  await page.getByRole('button', { name: 'Zastosuj' }).click()
  await expect(warunek1).toBeHidden()
  await expect(page.getByText('Metadane: 1 warunek')).toBeVisible()
  await expect(page.locator('[aria-label="Usuń filtr metadanych"]')).toBeVisible()
  await expect(fixtureRow).toBeVisible()
  await expect(pdfRow).toBeVisible()
  await expect(docxRow).toHaveCount(0)
  await expectNoLayoutDefects(page, 'lista z chipem filtra metadanych (SC-04 krok 2)')

  // Krok 3: drugi warunek `rok = 2023` przy „Spełnione: wszystkie” → 1 dokument (fixture).
  await page.getByRole('button', { name: 'Filtr metadanych' }).click({ timeout: 10_000 })
  await expect(warunek1).toBeVisible()
  // Stan roboczy kreatora przetrwał zamknięcie: warunek 1 dalej typ = raport.
  // toHaveValue, nie toContainText: elementText dla inputa tekstowego czyta textContent (zawsze '')
  // — Playwright 1.63 coreBundle.js; wartość pola weryfikuje dopiero toHaveValue (review T5b).
  await expect(warunek1.getByRole('combobox', { name: 'Klucz' })).toHaveValue('typ')
  await page.getByRole('button', { name: '+ Warunek' }).click()
  const warunek2 = page.getByRole('group', { name: 'Warunek 2' })
  await expect(warunek2).toBeVisible()
  await warunek2.getByRole('combobox', { name: 'Klucz' }).click()
  await page.getByRole('option', { name: 'rok', exact: true }).click()
  await warunek2.getByRole('combobox', { name: 'Operator' }).click()
  await page.getByRole('option', { name: '=', exact: true }).click()
  await warunek2.getByRole('combobox', { name: 'Wartość' }).click()
  await page.getByRole('option', { name: '2023' }).click()
  await page.getByRole('button', { name: 'Zastosuj' }).click()
  await expect(warunek1).toBeHidden()
  await expect(page.getByText('Metadane: 2 warunki')).toBeVisible()
  await expect(fixtureRow).toBeVisible()
  await expect(pdfRow).toHaveCount(0)
  await expect(docxRow).toHaveCount(0)

  // Krok 4 z odchyłki §6: dokument BEZ klucza nie pasuje do żadnego operatora — `not empty`
  // daje 2 dokumenty (fixture, PDF), a `empty` pusty wynik filtra (nie DOCX).
  await page.getByRole('button', { name: 'Filtr metadanych' }).click({ timeout: 10_000 })
  await warunek2.getByRole('button', { name: 'Usuń warunek' }).click()
  await expect(warunek2).toBeHidden()
  await warunek1.getByRole('combobox', { name: 'Operator' }).click()
  await page.getByRole('option', { name: 'not empty', exact: true }).click()
  // Pole wartości znika dla operatorów bez wartości.
  await expect(warunek1.getByRole('combobox', { name: 'Wartość' })).toHaveCount(0)
  await page.getByRole('button', { name: 'Zastosuj' }).click()
  await expect(fixtureRow).toBeVisible()
  await expect(pdfRow).toBeVisible()
  await expect(docxRow).toHaveCount(0)
  await page.getByRole('button', { name: 'Filtr metadanych' }).click({ timeout: 10_000 })
  await warunek1.getByRole('combobox', { name: 'Operator' }).click()
  await page.getByRole('option', { name: 'empty', exact: true }).click()
  await page.getByRole('button', { name: 'Zastosuj' }).click()
  await expect(page.getByText('Brak dokumentów spełniających filtr')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Wyczyść filtr' })).toBeVisible()

  // Krok 5: warunek bez dopasowań (`typ = ustawa`) → pusta tabela z akcją zdjęcia filtra,
  // NIE stan pustego datasetu z przyciskiem uploadu. Opcja `ustawa` pochodzi z enum pola
  // `typ` w konfiguracji datasetu (znane wartości dokumentów mają tylko `raport`).
  await page.getByRole('button', { name: 'Filtr metadanych' }).click({ timeout: 10_000 })
  await warunek1.getByRole('combobox', { name: 'Operator' }).click()
  await page.getByRole('option', { name: '=', exact: true }).click()
  await warunek1.getByRole('combobox', { name: 'Wartość' }).click()
  await page.getByRole('option', { name: 'ustawa' }).click()
  await page.getByRole('button', { name: 'Zastosuj' }).click()
  await expect(page.getByText('Brak dokumentów spełniających filtr')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Wyczyść filtr' })).toBeVisible()
  await expect(page.getByTestId('files-add')).toHaveCount(0)

  // Krok 6: × na chipie → pełna lista, kreator wyczyszczony.
  await page.locator('[aria-label="Usuń filtr metadanych"]').click()
  await expect(page.getByText(/^Metadane:/)).toHaveCount(0)
  await expect(fixtureRow).toBeVisible()
  await expect(pdfRow).toBeVisible()
  await expect(docxRow).toBeVisible()
  await page.getByRole('button', { name: 'Filtr metadanych' }).click({ timeout: 10_000 })
  await expect(warunek1).toBeVisible()
  // Kreator wyczyszczony: × czyści stan roboczy, świeży wiersz ma pusty klucz
  // (toHaveValue — jak wyżej, toContainText na inpucie tekstowym zawsze czyta '').
  await expect(warunek1.getByRole('combobox', { name: 'Klucz' })).toHaveValue('')
})

// Defekt QA E6-1b-4 (T10): wartość wpisana w kreatorze BEZ Enter jest wartością warunku —
// klik „Zastosuj" nie może użyć starej (pustej) wartości. Wpis „raport" bez Enter ma dać
// 2 dokumenty (fixture, PDF) i schować DOCX; bez commita warunek `typ = ''` dałby pusty wynik.
test('SC-E6-1b-04 defekt QA E6-1b-4 (T10): wartość wpisana bez Enter działa przy „Zastosuj"', async ({
  page,
  request,
}) => {
  test.setTimeout(300_000)
  const token = await adminToken(request)
  const { datasetId, name, pdfId } = await seedMetadataDataset(request, token, 'SC-04 T10')
  await patchDocMeta(request, token, datasetId, pdfId, { typ: 'raport' })

  await openFiles(page, datasetId, name)
  await page.getByRole('button', { name: 'Filtr metadanych' }).click({ timeout: 10_000 })
  const warunek1 = page.getByRole('group', { name: 'Warunek 1' })
  await expect(warunek1).toBeVisible()
  await warunek1.getByRole('combobox', { name: 'Klucz' }).click()
  await page.getByRole('option', { name: 'typ', exact: true }).click()
  await warunek1.getByRole('combobox', { name: 'Operator' }).click()
  await page.getByRole('option', { name: '=', exact: true }).click()
  // Istota defektu: wpisanie „raport" BEZ Enter i bez klikania opcji podpowiedzi.
  const wartosc = warunek1.getByRole('combobox', { name: 'Wartość' })
  await wartosc.click()
  await wartosc.pressSequentially('raport')
  await wartosc.click() // zamknięcie podpowiedzi — fokus zostaje w polu, Enter nigdy nie pada
  await page.getByRole('button', { name: 'Zastosuj' }).click()
  await expect(warunek1).toBeHidden()
  await expect(page.getByText('Metadane: 1 warunek')).toBeVisible()
  await expect(page.getByRole('row').filter({ hasText: FIXTURE_NAME })).toBeVisible()
  await expect(page.getByRole('row').filter({ hasText: PDF_NAME })).toBeVisible()
  await expect(page.getByRole('row').filter({ hasText: DOCX_NAME })).toHaveCount(0)
})

test.describe('SC-E6-1b-04 wariant 390 px: kreator w jednej kolumnie mieści się w oknie', () => {
  test.use({ viewport: { width: 390, height: 844 } })

  test('klucz nad operatorem i wartością, filtr zapisuje się', async ({ page, request }) => {
    test.setTimeout(300_000)
    const token = await adminToken(request)
    const { datasetId, name, pdfId } = await seedMetadataDataset(request, token, 'SC-04 390')
    await patchDocMeta(request, token, datasetId, pdfId, { typ: 'raport', region: 'mazowieckie' })

    await openFiles(page, datasetId, name)
    await page.getByRole('button', { name: 'Filtr metadanych' }).click({ timeout: 10_000 })
    const warunek1 = page.getByRole('group', { name: 'Warunek 1' })
    await expect(warunek1).toBeVisible()
    await warunek1.getByRole('combobox', { name: 'Klucz' }).click()
    await page.getByRole('option', { name: 'typ', exact: true }).click()
    await warunek1.getByRole('combobox', { name: 'Operator' }).click()
    await page.getByRole('option', { name: '=', exact: true }).click()
    await warunek1.getByRole('combobox', { name: 'Wartość' }).click()
    await page.getByRole('option', { name: 'raport' }).click()

    // Kreator w dwóch liniach: klucz nad (operator + wartość), wszystko w oknie 390 px.
    const kluczBox = await warunek1.getByRole('combobox', { name: 'Klucz' }).boundingBox()
    const operatorBox = await warunek1.getByRole('combobox', { name: 'Operator' }).boundingBox()
    const wartoscBox = await warunek1.getByRole('combobox', { name: 'Wartość' }).boundingBox()
    expect(kluczBox, 'pole „Klucz” widoczne w geometrii').not.toBeNull()
    expect(operatorBox, 'pole „Operator” widoczne w geometrii').not.toBeNull()
    expect(wartoscBox, 'pole „Wartość” widoczne w geometrii').not.toBeNull()
    expect(kluczBox!.y, 'klucz nad operatorem (układ w kolumnie)').toBeLessThan(operatorBox!.y)
    // E67-z2 (SC-z2-04): w wąskim kontenerze wiersz ma 2 linie — operator i wartość obok siebie pod kluczem.
    expect(
      Math.abs(operatorBox!.y - wartoscBox!.y),
      'operator i wartość w jednej linii',
    ).toBeLessThan(8)
    expect(operatorBox!.x + operatorBox!.width, 'operator przed wartością').toBeLessThanOrEqual(
      wartoscBox!.x + 1,
    )
    for (const [label, box] of [
      ['Klucz', kluczBox!],
      ['Operator', operatorBox!],
      ['Wartość', wartoscBox!],
    ] as const) {
      expect(box.x, `${label}: lewa krawędź w oknie`).toBeGreaterThanOrEqual(0)
      expect(box.x + box.width, `${label}: prawa krawędź w oknie 390 px`).toBeLessThanOrEqual(391)
    }
    await expectNoLayoutDefects(page, 'kreator filtra metadanych przy 390 px')

    await page.getByRole('button', { name: 'Zastosuj' }).click()
    await expect(warunek1).toBeHidden()
    await expect(page.getByText('Metadane: 1 warunek')).toBeVisible()
    await expectNoLayoutDefects(page, 'lista z chipem filtra przy 390 px')
  })
})

// ── Budżet SC-E6-1b (SCENARIOS.md „Budżety”): lista dokumentów z aktywnym filtrem na
// datasecie 200 dokumentów odpowiada ≤ 1 s. Dane przez API w teście (CONTRACT §5) — małe
// dokumenty wgrywane partiami (masowego helpera w e2e/helpers nie ma); parsowanie zbędne,
// bo filtr czyta `meta_fields` nadane PATCH-em, nie treść.
// Fallback z briefu T7: 200 dokumentów w czasie testu niewykonalne (bieg wyroczni 2026-10-13 —
// wgrywanie przez API nie zdążyło w timeout 5 min), pomiar na 50.
test.describe('SC-E6-1b-04 budżet: filtr na 50 dokumentach odpowiada ≤ 1 s (fallback z 200)', () => {
  test('„Zastosuj” → przefiltrowane dane na liście ≤ 1 s (50 dokumentów z API)', async ({
    page,
    request,
  }) => {
    test.setTimeout(300_000)
    const token = await adminToken(request)
    const name = `E2E S25 budżet ${uniq()}`
    const datasetId = await createDataset(request, token, name)
    cleanupDatasets.push(datasetId)
    const BUDGET_COUNT = 50
    const bytes = Buffer.from('Dokument pomiaru budżetu filtra metadanych (S6-15).', 'utf-8')
    // Wgrywanie i PATCH partiami po 25 (Promise.all). Meta zróżnicowane: filtr `typ = raport`
    // wybiera połowę zbioru.
    const ids: string[] = []
    for (let start = 0; start < BUDGET_COUNT; start += 25) {
      const batch = Array.from({ length: Math.min(25, BUDGET_COUNT - start) }, (_, i) => start + i)
      const uploaded = await Promise.all(
        batch.map(async (i) => {
          const docs = await ok<{ id: string }[]>(
            request.post(`${API_URL}/api/v1/datasets/${datasetId}/documents`, {
              headers: { authorization: `Bearer ${token}` },
              multipart: {
                file: {
                  name: `budzet-${String(i).padStart(3, '0')}.txt`,
                  mimeType: 'text/plain',
                  buffer: bytes,
                },
              },
            }),
            `POST …/documents (budzet-${String(i).padStart(3, '0')}.txt)`,
          )
          return docs[0]!.id
        }),
      )
      ids.push(...uploaded)
    }
    expect(ids, '50 dokumentów w datasecie pomiarowym').toHaveLength(50)
    for (let start = 0; start < ids.length; start += 25) {
      await Promise.all(
        ids.slice(start, start + 25).map((id, i) => {
          const index = start + i
          return patchDocMeta(request, token, datasetId, id, {
            typ: index % 2 === 0 ? 'raport' : 'protokol',
            rok: String(2019 + (index % 6)),
          })
        }),
      )
    }

    await openFiles(page, datasetId, name)
    // Lista załadowana przed pomiarem — mierzymy odpowiedź NA filtr, nie pierwszy load.
    await expect(page.getByRole('row').filter({ hasText: 'budzet-' }).first()).toBeVisible()
    await page.getByRole('button', { name: 'Filtr metadanych' }).click({ timeout: 10_000 })
    const warunek1 = page.getByRole('group', { name: 'Warunek 1' })
    await expect(warunek1).toBeVisible()
    await warunek1.getByRole('combobox', { name: 'Klucz' }).click()
    await page.getByRole('option', { name: 'typ', exact: true }).click()
    await warunek1.getByRole('combobox', { name: 'Operator' }).click()
    await page.getByRole('option', { name: '=', exact: true }).click()
    await warunek1.getByRole('combobox', { name: 'Wartość' }).click()
    await page.getByRole('option', { name: 'raport' }).click()

    // Pomiar: klik „Zastosuj” → odpowiedź `GET …/documents?metadata_condition=…` (dane, które
    // dostaje lista) + chip filtra ≤ 1 s. Chip renderuje się z commitu stanu, więc mierzonym
    // sygnałem jest przede wszystkim odpowiedź zapytania listy. Nasłuch UZBROJONY PRZED
    // klikiem: lokalne API odpowiada w kilka ms, szybciej niż roundtrip protokołu Playwrighta
    // po `click()` — rejestrowany po kliku nasłuch traci wyścig i czeka do timeoutu testu
    // (dwa razy z rzędu w biegu wyroczni 2026-10-13).
    const startedAt = Date.now()
    const responsePromise = page.waitForResponse((r) => r.url().includes('metadata_condition='), {
      timeout: 30_000,
    })
    await page.getByRole('button', { name: 'Zastosuj' }).click()
    const response = await responsePromise
    const body = (await response.body()).toString()
    await expect(page.getByText('Metadane: 1 warunek')).toBeVisible()
    const elapsed = Date.now() - startedAt
    expect(JSON.parse(body).data.total, 'filtr wybiera połowę zbioru (25 z 50)').toBe(25)
    await expect(page.getByRole('row').filter({ hasText: 'budzet-' }).first()).toBeVisible()
    // Dokument `protokol` nie pasuje do żadnego warunku — na przefiltrowanej liście go nie ma.
    await expect(page.getByRole('row').filter({ hasText: 'budzet-049' })).toHaveCount(0, {
      timeout: 15_000,
    })
    expect(
      elapsed,
      'budżet SC-E6-1b: lista z filtrem odpowiada ≤ 1 s (pomiar na 50 dokumentach)',
    ).toBeLessThanOrEqual(1000)
  })
})

test.describe('SC-E6-1b-04 wariant F5: filtr w stanie komponentu — po odświeżeniu resetuje się', () => {
  // Filtry listy plików żyją w stanie komponentu (`useState` w `DatasetFilesTab`), nie w URL —
  // odchyłka §6: filtr metadanych zachowuje się jak reszta, więc F5 resetuje filtr.
  test('po odświeżeniu chip znika, lista wraca do pełnej', async ({ page, request }) => {
    test.setTimeout(300_000)
    const token = await adminToken(request)
    const { datasetId, name, pdfId } = await seedMetadataDataset(request, token, 'SC-04 F5')
    await patchDocMeta(request, token, datasetId, pdfId, { typ: 'raport', region: 'mazowieckie' })

    await openFiles(page, datasetId, name)
    await page.getByRole('button', { name: 'Filtr metadanych' }).click({ timeout: 10_000 })
    const warunek1 = page.getByRole('group', { name: 'Warunek 1' })
    await expect(warunek1).toBeVisible()
    await warunek1.getByRole('combobox', { name: 'Klucz' }).click()
    await page.getByRole('option', { name: 'typ', exact: true }).click()
    await warunek1.getByRole('combobox', { name: 'Operator' }).click()
    await page.getByRole('option', { name: '=', exact: true }).click()
    await warunek1.getByRole('combobox', { name: 'Wartość' }).click()
    await page.getByRole('option', { name: 'raport' }).click()
    await page.getByRole('button', { name: 'Zastosuj' }).click()
    await expect(page.getByText('Metadane: 1 warunek')).toBeVisible()
    const docxRow = page.getByRole('row').filter({ hasText: DOCX_NAME })
    await expect(docxRow).toHaveCount(0)

    await page.reload()
    await expect(page.getByRole('heading', { name })).toBeVisible()
    await expect(page.getByText(/^Metadane:/)).toHaveCount(0)
    await expect(page.getByRole('row').filter({ hasText: FIXTURE_NAME })).toBeVisible()
    await expect(page.getByRole('row').filter({ hasText: PDF_NAME })).toBeVisible()
    await expect(docxRow).toBeVisible()
  })
})
