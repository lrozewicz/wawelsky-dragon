// Scenariusz S6-06b (brief E5-H3 #9, CONTRACT WP E5-H3 §„Plan testów e2e"): parser PDF = model
// image2text (`fake-vision`) i zakres stron. Dataset A ustawiany przez UI Konfiguracji (select
// `pdf-parser-select` = `fake-vision`, zakres stron 2–2, zapis, przeładowanie = utrwalone);
// dataset B z parserem ustawionym przez API bez zakresu. Do obu wgrywamy ten sam 3-stronicowy
// PDF przez API, parsujemy do „Sukces" i porównujemy chunki: B daje trzy różne `OCR:<sha8>`
// (po jednym na stronę), A dokładnie jeden — równy środkowemu z B (strona 2, `pages [[2,2]]`).
// Uzasadnienie: `layout_recognize` ≠ DeepDOC/Plain Text → tryb wizji (`ingest_pipeline.py`),
// a `fake-vision` odpowiada `OCR:sha256(bajty renderu strony)[:8]` (K10 §4).
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import type { APIRequestContext, APIResponse } from '@playwright/test'

import { expect, test } from './fixtures'
import { POLL_TIMEOUT_MS, apiLogin, createDataset, loginViaUi } from './helpers'
import { listChunks } from './helpers/chunks'
import type { ListedChunk } from './helpers/chunks'

const API_URL = process.env.WD_E2E_API_URL ?? ''

const UI_NAME = 'E2E S6-06b parser przez UI'
const API_NAME = 'E2E S6-06b parser przez API'
const DOCUMENT_NAME = 'three-pages.pdf'
const VISION_PARSER = 'fake-vision'

/** Fixture zacommitowany w `e2e/fixtures` (3 strony różnym tekstem; `PDF_PAGES` stron niżej). */
const PDF_PATH = fileURLToPath(new URL('./fixtures/three-pages.pdf', import.meta.url))
const PDF_PAGES = 3

const sleep = (ms: number): Promise<void> => new Promise((resolve) => setTimeout(resolve, ms))

type Envelope<T> = { code: number; message: string; data: T }

/** Rozwija kopertę RAGFlow (jak `helpers.ts`): HTTP 200 + `code 0`, inaczej `expect` rzuca. */
async function ok<T>(pending: Promise<APIResponse>, label: string): Promise<T> {
  const response = await pending
  const body = (await response.json()) as Envelope<T>
  expect(response.status(), `${label}: HTTP ${response.status()} — ${body.message}`).toBe(200)
  expect(body.code, `${label}: ${body.message}`).toBe(0)
  return body.data
}

/** Ustawia sam `layout_recognize` przez PUT — dataset B nie przechodzi przez UI (kontrakt §T4). */
async function setVisionParser(
  request: APIRequestContext,
  token: string,
  datasetId: string,
): Promise<void> {
  await ok<unknown>(
    request.put(`${API_URL}/api/v1/datasets/${datasetId}`, {
      headers: { authorization: `Bearer ${token}` },
      data: { parser_config: { layout_recognize: VISION_PARSER } },
    }),
    'PUT /api/v1/datasets/{id}',
  )
}

/** Wgrywa `three-pages.pdf` przez API i zwraca id dokumentu. */
async function uploadPdf(
  request: APIRequestContext,
  token: string,
  datasetId: string,
): Promise<string> {
  const uploaded = await ok<{ id: string }[]>(
    request.post(`${API_URL}/api/v1/datasets/${datasetId}/documents`, {
      headers: { authorization: `Bearer ${token}` },
      multipart: {
        file: {
          name: DOCUMENT_NAME,
          mimeType: 'application/pdf',
          buffer: readFileSync(PDF_PATH),
        },
      },
    }),
    'POST /api/v1/datasets/{id}/documents',
  )
  expect(uploaded, 'upload zwrócił dokładnie jeden dokument').toHaveLength(1)
  return uploaded[0]!.id
}

/** Startuje parsowanie i czeka (do 90 s) na `run = DONE` — „Sukces" w UI (jak `seedCorpus`). */
async function parseAndWait(
  request: APIRequestContext,
  token: string,
  datasetId: string,
  documentId: string,
): Promise<void> {
  const headers = { authorization: `Bearer ${token}` }
  await ok<unknown>(
    request.post(`${API_URL}/api/v1/datasets/${datasetId}/documents/parse`, {
      headers,
      data: { document_ids: [documentId] },
    }),
    'POST /api/v1/datasets/{id}/documents/parse',
  )
  const deadline = Date.now() + POLL_TIMEOUT_MS
  let run = ''
  while (Date.now() < deadline) {
    const listed = await ok<{ docs: { run: string }[] }>(
      request.get(`${API_URL}/api/v1/datasets/${datasetId}/documents?id=${documentId}`, {
        headers,
      }),
      'GET /api/v1/datasets/{id}/documents',
    )
    run = listed.docs[0]?.run ?? ''
    if (run === 'DONE' || run === 'FAIL' || run === 'CANCEL') break
    await sleep(1_000)
  }
  expect(run, 'stan parsowania dokumentu (DONE = „Sukces" w UI)').toBe('DONE')
}

/** Skróty `OCR:<sha8>` z treści chunków, w kolejności stron, bez powtórzeń. */
function ocrShas(chunks: ListedChunk[]): string[] {
  const pattern = /OCR:([0-9a-f]{8})/g
  const ordered: string[] = []
  for (const chunk of chunks) {
    for (const match of chunk.content.matchAll(pattern)) {
      const sha = match[1]!
      if (!ordered.includes(sha)) ordered.push(sha)
    }
  }
  return ordered
}

test('S6-06b: parser image2text w UI + zakres stron 2–2 ogranicza chunki do środkowej strony', async ({
  page,
  request,
}) => {
  // Dwa parsowania (odpytywanie po 90 s) i interakcje z UI — jak S6-06/S6-07.
  test.setTimeout(300_000)

  const token = await apiLogin(request)
  const uiId = await createDataset(request, token, UI_NAME)
  const apiId = await createDataset(request, token, API_NAME)

  // 1. Dataset A: ustawienia przez UI Konfiguracji — parser = fake-vision, zakres stron 2–2.
  await loginViaUi(page)
  await page.goto(`/dataset/configuration/${uiId}`)
  await expect(page.getByRole('heading', { name: UI_NAME })).toBeVisible()

  // Wybór modelu image2text w selekcie „Parser PDF" (T3 dodaje `pdf-parser-select` i opcje modeli).
  // Regresja T11 (2026-10-11): klik w sam testid (FormControl) nie otwiera menu — centrum pola
  // wypada między combobox a dwuwierszową podpowiedzią „Dotyczy nowych plików” (E5-H8c), a obsługa
  // mousedown jest tylko na wewnętrznym divie combobox (MUI 9). Klikamy więc w ten element.
  await expect(page.getByTestId('pdf-parser-select')).toBeVisible()
  await page.getByTestId('pdf-parser-select').getByRole('combobox').click()
  await page.getByRole('option', { name: VISION_PARSER }).click()

  // Jeden zakres 2–2 (kolumna „Od"/„Do" wiersza 0).
  await page.getByTestId('pages-add').click()
  await page.getByTestId('pages-from-0').fill('2')
  await page.getByTestId('pages-to-0').fill('2')

  await page.getByRole('button', { name: 'Zapisz' }).click()
  await expect(page.getByText('Zapisano')).toBeVisible()

  // 2. F5 — wartości wracają z backendu (PUT utrwalił parser i zakres).
  await page.reload()
  await expect(page.getByRole('heading', { name: UI_NAME })).toBeVisible()
  await expect(page.getByTestId('pdf-parser-select')).toContainText(VISION_PARSER)
  expect(await page.getByTestId('pages-from-0').inputValue()).toBe('2')
  expect(await page.getByTestId('pages-to-0').inputValue()).toBe('2')

  // 3. Dataset B: ten sam parser, ale bez zakresu — ustawiony przez API (kontrakt §T4).
  await setVisionParser(request, token, apiId)

  // 4. Upload tego samego PDF-a do obu datasetów i parsowanie do „Sukces".
  const uiDoc = await uploadPdf(request, token, uiId)
  const apiDoc = await uploadPdf(request, token, apiId)
  await parseAndWait(request, token, apiId, apiDoc)
  await parseAndWait(request, token, uiId, uiDoc)

  // Użytkownik widzi w siatce plików datasetu A status „Sukces" (jak S6-03).
  await page.goto(`/dataset/files/${uiId}`)
  await expect(page.getByRole('heading', { name: UI_NAME })).toBeVisible()
  await expect(page.locator('[data-testid^="status-cell-"]')).toHaveText('Sukces', {
    timeout: POLL_TIMEOUT_MS,
  })

  // 5. Chunki: B bez zakresu → po jednym `OCR:<sha8>` na stronę (3 różne); A z [[2,2]] → tylko
  //    środkowa strona (drugi skrót z B). Kolejność: `ORDER BY ordinal` + treść stron 1→3.
  const allShas = ocrShas(await listChunks(request, token, apiId, apiDoc))
  expect(allShas, `dataset bez zakresu powinien dać ${PDF_PAGES} różne skróty OCR`).toHaveLength(
    PDF_PAGES,
  )
  const rangedShas = ocrShas(await listChunks(request, token, uiId, uiDoc))
  expect(
    rangedShas,
    'dataset z zakresem [[2,2]] powinien dać dokładnie jeden skrót OCR',
  ).toHaveLength(1)
  expect(
    rangedShas[0],
    'zakres [[2,2]] = środkowa strona (drugi skrót z datasetu bez zakresu)',
  ).toBe(allShas[1])
})
