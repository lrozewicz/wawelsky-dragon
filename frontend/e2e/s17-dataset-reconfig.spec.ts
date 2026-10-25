// Scenariusze E5-H8c (CONTRACT WP E5-H8c §2 i §3, SCENARIOS.md SC-01/02): zmiana konfiguracji
// datasetu przy wgranych plikach — podpowiedź „Dotyczy nowych plików”, dialog „Zastosować zmiany
// do istniejących plików?” po zapisie („Tylko nowe pliki” / „Zastosuj i parsuj ponownie”) oraz
// dialog „Metoda chunkowania” pliku pokazujący FAKTYCZNĄ konfigurację pliku (parser PDF + zakres
// stron). Na bazie (bez implementacji T4/T5) testy są CZERWONE z właściwej przyczyny: brak
// podpowiedzi i brak dialogu zastosowania do istniejących plików, brak pól parsera/zakresu
// w dialogu pliku. Wzorce: s06b-pdf-parser-pages.spec.ts (upload API, parse do DONE).
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import type { APIRequestContext, APIResponse, Page } from '@playwright/test'

import { expect, test } from './fixtures'
import { POLL_TIMEOUT_MS, apiLogin, createDataset } from './helpers'
import { listChunks } from './helpers/chunks'
import type { ListedChunk } from './helpers/chunks'
import { deleteDataset } from './helpers/files'
import { expectNoLayoutDefects } from './helpers/layout'
import { setProfileLanguage } from './helpers/models'
import { uiSession } from './helpers/session'

const API_URL = process.env.WD_E2E_API_URL ?? ''

const DOCUMENT_NAME = 'three-pages.pdf'
const VISION_PARSER = 'fake-vision'
const APPLY_TITLE = 'Zastosować zmiany do istniejących plików?'
const HELPER_TEXT = 'Dotyczy nowych plików'

/** Fixture zacommitowany w `e2e/fixtures` (3 strony różnym tekstem — jak s06b). */
const PDF_PATH = fileURLToPath(new URL('./fixtures/three-pages.pdf', import.meta.url))

const sleep = (ms: number): Promise<void> => new Promise((resolve) => setTimeout(resolve, ms))

/** Unikalna nazwa datasetu — reset K9 biegnie raz na bieg, sprzątanie w afterEach. */
function uniq(): string {
  return `${Date.now()}-${Math.floor(Math.random() * 1_000_000)}`
}

/**
 * Współdzielony token admina na cały bieg pliku: limiter logowań liczy KAŻDĄ próbę
 * (10/min per IP+e-mail, CONTRACT E5-2a §4), a testy padają na bazie szybko — świeże
 * logowanie w każdym teście i afterEach tripiło 429 i zanieczyszczało przyczyny czerwieni.
 */
let adminTokenPromise: Promise<string> | undefined
function adminToken(request: APIRequestContext): Promise<string> {
  adminTokenPromise ??= apiLogin(request)
  return adminTokenPromise
}

// Logowanie RAZ na plik (T11): limiter logowań (10/min per IP+e-mail) jest współdzielony
// z całym biegiem verify-full, a plik loguje się UI-owo w każdym teście. Testy startują
// z sesją z `storageState`; `afterEach` zapisuje stan po rotacji cookie `wd_refresh`
// (reuse zużytego tokenu → 401 rodziny, C9); testy biegną sekwencyjnie (workers = 1).
const session = uiSession('s17-dataset-reconfig')
test.use({ storageState: session.statePath })
test.beforeAll(async ({ browser }) => {
  await session.login(browser)
})
test.afterEach(async ({ context }) => {
  await session.save(context)
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

test.afterEach(async ({ request }) => {
  const token = await adminToken(request)
  // Wariant EN zmienia język profilu — przywracamy PL, żeby kolejne testy widziały etykiety PL.
  await setProfileLanguage(request, token, 'pl')
  for (const id of cleanupDatasets.splice(0)) {
    await deleteDataset(request, token, id)
  }
})

/**
 * Dataset z parserem wizji i zakresem stron ustawionymi PRZED uploadem (SC-01 krok 1).
 * Zwraca id i nazwę datasetu (nagłówek zakładki Konfiguracja).
 */
async function seedDataset(
  request: APIRequestContext,
  token: string,
  pages: [number, number][],
  scenario: 'SC-01' | 'SC-02',
): Promise<{ datasetId: string; name: string }> {
  const name = `E2E S17 ${scenario} ${uniq()}`
  const datasetId = await createDataset(request, token, name)
  cleanupDatasets.push(datasetId)
  await ok<unknown>(
    request.put(`${API_URL}/api/v1/datasets/${datasetId}`, {
      headers: { authorization: `Bearer ${token}` },
      data: { parser_config: { layout_recognize: VISION_PARSER, pages } },
    }),
    'PUT /api/v1/datasets/{id}',
  )
  return { datasetId, name }
}

/** Wgrywa `three-pages.pdf` przez API i zwraca id dokumentu (wzór: s06b). */
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

/** Startuje parsowanie i czeka (do 90 s) na `run = DONE` — „Sukces” w UI (wzór: s06b). */
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
  expect(run, 'stan parsowania dokumentu (DONE = „Sukces” w UI)').toBe('DONE')
}

/** Dokument z listy datasetu: stan parsowania i `parser_config` pliku. */
async function getDocument(
  request: APIRequestContext,
  token: string,
  datasetId: string,
  documentId: string,
): Promise<{ run: string; parser_config: Record<string, unknown> }> {
  const listed = await ok<{ docs: { run: string; parser_config: Record<string, unknown> }[] }>(
    request.get(`${API_URL}/api/v1/datasets/${datasetId}/documents?id=${documentId}`, {
      headers: { authorization: `Bearer ${token}` },
    }),
    'GET /api/v1/datasets/{id}/documents',
  )
  expect(listed.docs, 'dokument na liście datasetu').toHaveLength(1)
  return listed.docs[0]!
}

/** Skróty `OCR:<sha8>` z treści chunków (po jednym na stronę renderu wizji, wzór: s06b). */
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

/** Zakładka „Konfiguracja” datasetu z nagłówkiem nazwy (sesja z `storageState`, bez logowania). */
async function openConfig(page: Page, datasetId: string, name: string): Promise<void> {
  await page.goto(`/dataset/configuration/${datasetId}`)
  await expect(page.getByRole('heading', { name })).toBeVisible()
}

/** Okno „Zastosować zmiany do istniejących plików?” (kontrakt §2: rola dialog, nazwa = title). */
function applyDialog(page: Page) {
  return page.getByRole('dialog', { name: APPLY_TITLE })
}

test('SC-E5-H8c-01 podpowiedź „Dotyczy nowych plików”, dialog po zapisie, „Tylko nowe pliki”', async ({
  page,
  request,
}) => {
  // Dwa parsowania w przygotowaniu i asercje UI — zapas ponad domyślne 30 s (jak s06b).
  test.setTimeout(300_000)
  const token = await adminToken(request)
  const { datasetId, name } = await seedDataset(request, token, [[2, 3]], 'SC-01')
  const docId = await uploadPdf(request, token, datasetId)
  await parseAndWait(request, token, datasetId, docId)
  const before = ocrShas(await listChunks(request, token, datasetId, docId))
  expect(before, 'zakres 2–3: dwa skróty OCR (strony 2 i 3)').toHaveLength(2)

  await openConfig(page, datasetId, name)

  // Krok 1: pod „Metoda chunkowania”, „Parser PDF”, „Zakres stron” podpowiedź z makiety.
  await expect(page.getByText(HELPER_TEXT)).toHaveCount(3)

  await expectNoLayoutDefects(page, 'konfiguracja datasetu z podpowiedziami (SC-01 krok 1)')

  // Krok 2: usuwa zakres stron, klika „Zapisz” → dialog z listą zmienionych pól i liczbą plików.
  await page.getByTestId('pages-remove-0').click()
  await page.getByRole('button', { name: 'Zapisz' }).click()
  const dialog = applyDialog(page)
  await expect(dialog).toBeVisible()
  await expect(dialog).toContainText('Zakres stron')
  await expect(dialog).toContainText('Dataset ma 1 plik')
  await expectNoLayoutDefects(page, 'dialog „Zastosować zmiany…” (SC-01 krok 2)')

  // Krok 3: „Tylko nowe pliki” → zapis datasetu; plik bez zmian (te same chunki i `parser_config`).
  await dialog.getByRole('button', { name: 'Tylko nowe pliki' }).click()
  await expect(dialog).toBeHidden()
  await expect(page.getByText('Zapisano')).toBeVisible()
  expect(ocrShas(await listChunks(request, token, datasetId, docId)), 'chunki bez zmian').toEqual(
    before,
  )
  const document = await getDocument(request, token, datasetId, docId)
  expect(document.parser_config.pages, 'zakres pliku bez zmian').toEqual([[2, 3]])

  // Krok 5: zapis bez zmiany tych pól (tylko opis) → brak dialogu.
  await page.getByLabel('Opis').fill('Zmiana tylko opisu — bez dialogu')
  await page.getByRole('button', { name: 'Zapisz' }).click()
  await expect(page.getByText('Zapisano')).toBeVisible()
  await expect(applyDialog(page)).toHaveCount(0)
})

test('SC-E5-H8c-01 po zapisie i powrocie z zakładki Pliki formularz pokazuje zapisane wartości', async ({
  page,
  request,
}) => {
  // Dataset bez plików (brief: „z plikiem lub bez”): zapis bez dialogu zastosowania, szybki bieg.
  const token = await adminToken(request)
  const name = `E2E S17 SC-01 stale ${uniq()}`
  const datasetId = await createDataset(request, token, name)
  cleanupDatasets.push(datasetId)

  await openConfig(page, datasetId, name)

  // Zakres stron 2–3 przez UI: „Dodaj zakres” + pola Od/Do.
  await page.getByTestId('pages-add').click()
  await page.getByTestId('pages-from-0').fill('2')
  await page.getByTestId('pages-to-0').fill('3')
  await page.getByRole('button', { name: 'Zapisz' }).click()
  await expect(page.getByText('Zapisano')).toBeVisible()
  // Bez plików dialog „Zastosować zmiany…” nie ma prawa się otworzyć.
  await expect(applyDialog(page)).toHaveCount(0)

  // Jak użytkownik: zakładka „Pliki”, potem powrót na „Konfigurację” klikami w zakładki.
  await page.getByRole('tab', { name: 'Pliki' }).click()
  await expect(page.getByRole('heading', { name })).toBeVisible()
  await page.getByRole('tab', { name: 'Konfiguracja' }).click()

  // Formularz ma pokazać ZAPISANE wartości (wiersz 2–3), nie stan sprzed zapisu (QA-UI #3).
  await expect(page.getByTestId('pages-from-0')).toHaveValue('2')
  await expect(page.getByTestId('pages-to-0')).toHaveValue('3')
})

test('SC-E5-H8c-01 „Zastosuj i parsuj ponownie (1)”: plik w „Sukces” z chunkami wszystkich stron', async ({
  page,
  request,
}) => {
  test.setTimeout(300_000)
  const token = await adminToken(request)
  const { datasetId, name } = await seedDataset(request, token, [[2, 3]], 'SC-01')
  const docId = await uploadPdf(request, token, datasetId)
  await parseAndWait(request, token, datasetId, docId)
  const beforeChunks = await listChunks(request, token, datasetId, docId)
  expect(ocrShas(beforeChunks), 'zakres 2–3: dwa skróty OCR').toHaveLength(2)

  await openConfig(page, datasetId, name)

  // Krok 4: zmienia zakres ponownie (1–3 = wszystkie strony), „Zapisz” → dialog → „Zastosuj…”.
  await page.getByTestId('pages-from-0').fill('1')
  await page.getByTestId('pages-to-0').fill('3')
  await page.getByRole('button', { name: 'Zapisz' }).click()
  const dialog = applyDialog(page)
  await expect(dialog).toBeVisible()
  await dialog.getByRole('button', { name: 'Zastosuj i parsuj ponownie (1)' }).click()
  await expect(dialog).toBeHidden()

  // Plik przechodzi w „Parsowanie” → „Sukces”; chunki odpowiadają wszystkim 3 stronom.
  // O liczbę STRON świadczą unikalne skróty OCR (3 po zmianie na 1–3 wobec 2 przy 2–3), nie
  // liczba chunków — backend scala krótkie strony w jeden chunk (bieg T6 2026-10-10, trace).
  await page.goto(`/dataset/files/${datasetId}`)
  await expect(page.getByTestId(`status-cell-${docId}`)).toContainText('Sukces', {
    timeout: POLL_TIMEOUT_MS,
  })
  // Ponowne parsowanie biegnie w tle; „Sukces” w komórce bywa jeszcze stary (wyścig
  // odświeżenia listy), więc o nowym zestawie chunków rozstrzyga poll po API.
  await expect
    .poll(async () => ocrShas(await listChunks(request, token, datasetId, docId)), {
      timeout: POLL_TIMEOUT_MS,
    })
    .toHaveLength(3)

  await expectNoLayoutDefects(page, 'zakładka Pliki po ponownym parsowaniu (SC-01 krok 4)')
})

test('SC-E5-H8c-01 wariant: podwójny klik „Zastosuj i parsuj ponownie” → jedno parsowanie pliku', async ({
  page,
  request,
}) => {
  test.setTimeout(300_000)
  const token = await adminToken(request)
  const { datasetId, name } = await seedDataset(request, token, [[2, 3]], 'SC-01')
  const docId = await uploadPdf(request, token, datasetId)
  await parseAndWait(request, token, datasetId, docId)

  await openConfig(page, datasetId, name)

  // Licznik POST …/datasets/{id}/chunks — podwójny klik ma wywołać JEDNO parsowanie na plik.
  let chunksPosts = 0
  page.on('request', (req) => {
    if (req.method() === 'POST' && req.url().includes(`/api/v1/datasets/${datasetId}/chunks`)) {
      chunksPosts += 1
    }
  })

  await page.getByTestId('pages-from-0').fill('1')
  await page.getByTestId('pages-to-0').fill('3')
  await page.getByRole('button', { name: 'Zapisz' }).click()
  const dialog = applyDialog(page)
  await expect(dialog).toBeVisible()
  await dialog.getByRole('button', { name: 'Zastosuj i parsuj ponownie (1)' }).dblclick()
  await expect(dialog).toBeHidden({ timeout: POLL_TIMEOUT_MS })
  expect(chunksPosts, 'POST …/chunks dokładnie raz dla 1 pliku').toBe(1)

  // Jak użytkownik: po zastosowaniu zagląda na listę plików (status-cell jest w zakładce Pliki).
  await page.goto(`/dataset/files/${datasetId}`)
  await expect(page.getByTestId(`status-cell-${docId}`)).toContainText('Sukces', {
    timeout: POLL_TIMEOUT_MS,
  })
  await expect
    .poll(async () => ocrShas(await listChunks(request, token, datasetId, docId)), {
      timeout: POLL_TIMEOUT_MS,
    })
    .toHaveLength(3)

  await expectNoLayoutDefects(page, 'zakładka Pliki po podwójnym kliku „Zastosuj…”')
})

test('SC-E5-H8c-01 wariant: Esc zamyka dialog „Zastosować zmiany…”; dataset zapisany, pliki bez zmian', async ({
  page,
  request,
}) => {
  test.setTimeout(300_000)
  const token = await adminToken(request)
  const { datasetId, name } = await seedDataset(request, token, [[2, 3]], 'SC-01')
  const docId = await uploadPdf(request, token, datasetId)
  await parseAndWait(request, token, datasetId, docId)
  const before = ocrShas(await listChunks(request, token, datasetId, docId))
  expect(before, 'zakres 2–3: dwa skróty OCR').toHaveLength(2)

  await openConfig(page, datasetId, name)
  await page.getByTestId('pages-remove-0').click()
  await page.getByRole('button', { name: 'Zapisz' }).click()
  const dialog = applyDialog(page)
  await expect(dialog).toBeVisible()

  // Esc zamyka dialog; zapis datasetu (PUT) już się dokonał — to tylko rezygnacja z zastosowania.
  await page.keyboard.press('Escape')
  await expect(dialog).toBeHidden()
  await expect(page.getByText('Zapisano')).toBeVisible()

  // Plik bez zmian: te same chunki i zakres 2–3 w parser_config pliku.
  expect(ocrShas(await listChunks(request, token, datasetId, docId)), 'chunki bez zmian').toEqual(
    before,
  )
  const document = await getDocument(request, token, datasetId, docId)
  expect(document.parser_config.pages, 'zakres pliku bez zmian').toEqual([[2, 3]])
})

test.describe('SC-E5-H8c-01 warianty wyglądu i języka', () => {
  test.describe('390 px + ciemny', () => {
    test.use({ viewport: { width: 390, height: 844 }, colorScheme: 'dark' })

    test('wariant 390 px + ciemny: podpowiedź i dialog mieszczą się w ekranie', async ({
      page,
      request,
    }) => {
      test.setTimeout(300_000)
      const token = await adminToken(request)
      const { datasetId, name } = await seedDataset(request, token, [[2, 3]], 'SC-01')
      const docId = await uploadPdf(request, token, datasetId)
      await parseAndWait(request, token, datasetId, docId)

      await openConfig(page, datasetId, name)

      // Podpowiedź pod każdym z trzech pól (krok 1), dialog po zapisie w całości w oknie 390 px.
      await expect(page.getByText(HELPER_TEXT)).toHaveCount(3)
      await page.getByTestId('pages-remove-0').click()
      await page.getByRole('button', { name: 'Zapisz' }).click()
      const dialog = applyDialog(page)
      await expect(dialog).toBeVisible()
      await expectNoLayoutDefects(page, 'dialog zastosowania przy 390 px w ciemnym motywie')
      await dialog.getByRole('button', { name: 'Tylko nowe pliki' }).click()
      await expect(dialog).toBeHidden()
      await expect(page.getByText('Zapisano')).toBeVisible()
      // Kończymy na górze formularza: AppBar jest `position="fixed"`, więc strażnik układu na
      // ekranie przewiniętym do „Zapisz” widzi wstążkę na polach, które pod nią przewinęły się
      // (bieg T6 2026-10-10) — to artefakt przewinięcia, nie wada ekranu.
      await page.evaluate(() => window.scrollTo(0, 0))
    })
  })

  test('wariant EN: „Applies to new files”, „Apply changes to existing files?”', async ({
    page,
    request,
  }) => {
    test.setTimeout(300_000)
    // Profil admina nadpisuje locale przeglądarki po zalogowaniu (authState.applyUser).
    const token = await adminToken(request)
    await setProfileLanguage(request, token, 'en')
    const { datasetId, name } = await seedDataset(request, token, [[2, 3]], 'SC-01')
    const docId = await uploadPdf(request, token, datasetId)
    await parseAndWait(request, token, datasetId, docId)

    await page.goto(`/dataset/configuration/${datasetId}`)
    await expect(page.getByRole('heading', { name })).toBeVisible()

    await expect(page.getByText('Applies to new files')).toHaveCount(3)
    await page.getByTestId('pages-remove-0').click()
    await page.getByRole('button', { name: 'Save' }).click()
    const dialog = page.getByRole('dialog', { name: 'Apply changes to existing files?' })
    await expect(dialog).toBeVisible()
    await expect(dialog).toContainText('Page ranges')
    await expectNoLayoutDefects(page, 'dialog zastosowania (EN)')
    await dialog.getByRole('button', { name: 'New files only' }).click()
    await expect(dialog).toBeHidden()
    await expect(page.getByText('Saved')).toBeVisible()
  })
})

test('SC-E5-H8c-02 dialog pliku pokazuje konfigurację pliku; zapis 1–3 → chunki wszystkich stron', async ({
  page,
  request,
}) => {
  test.setTimeout(300_000)
  const token = await adminToken(request)
  const { datasetId, name } = await seedDataset(request, token, [[2, 3]], 'SC-02')
  const docId = await uploadPdf(request, token, datasetId)
  await parseAndWait(request, token, datasetId, docId)
  const before = ocrShas(await listChunks(request, token, datasetId, docId))
  expect(before, 'zakres 2–3: dwa skróty OCR').toHaveLength(2)

  // Zakres w datasecie usunięty z „Tylko nowe pliki” — plik zachowuje zakres 2–3.
  await openConfig(page, datasetId, name)
  await page.getByTestId('pages-remove-0').click()
  await page.getByRole('button', { name: 'Zapisz' }).click()
  const apply = applyDialog(page)
  await expect(apply).toBeVisible()
  await apply.getByRole('button', { name: 'Tylko nowe pliki' }).click()
  await expect(apply).toBeHidden()
  await expect(page.getByText('Zapisano')).toBeVisible()

  // Krok 1: ⋮ przy pliku → „Metoda chunkowania” (przy 1280 px kolumna z chipem jest ukryta); dialog pokazuje
  // parser PDF i zakres 2–3 PLIKU, nie pusty zakres datasetu.
  await page.goto(`/dataset/files/${datasetId}`)
  const row = page.getByRole('row').filter({ hasText: DOCUMENT_NAME })
  await expect(row).toBeVisible()
  await row.getByTestId('row-actions-menu').click()
  await page.getByRole('menuitem', { name: 'Metoda chunkowania' }).click()
  const dialog = page.getByRole('dialog', { name: 'Metoda chunkowania' })
  await expect(dialog).toBeVisible()
  await expect(dialog.getByTestId('doc-pdf-parser-select')).toContainText(VISION_PARSER)
  await expect(dialog.getByTestId('pages-from-0')).toHaveValue('2')
  await expect(dialog.getByTestId('pages-to-0')).toHaveValue('3')
  await expectNoLayoutDefects(page, 'dialog „Metoda chunkowania” pliku (SC-02 krok 1)')

  // Krok 2: zmienia zakres na 1–3, zapisuje, parsuje → „Sukces”, chunki ze stron 1–3.
  await dialog.getByTestId('pages-from-0').fill('1')
  await dialog.getByTestId('pages-to-0').fill('3')
  await dialog.getByTestId('method-save').click()
  await expect(dialog).toBeHidden()
  const document = await getDocument(request, token, datasetId, docId)
  expect(document.parser_config.pages, 'zakres pliku po zapisie dialogu').toEqual([[1, 3]])
  await page.getByTestId(`status-parse-${docId}`).click()
  // Plik ma chunki — wiersz pyta o potwierdzenie przed ponownym parsowaniem (E3-3b §T7).
  await page.getByTestId('reparse-confirm').click()
  await expect(page.getByTestId(`status-cell-${docId}`)).toContainText('Sukces', {
    timeout: POLL_TIMEOUT_MS,
  })
  // „Sukces” bywa jeszcze stary (wyścig odświeżenia) — poll po API czeka na chunki 1–3.
  await expect
    .poll(async () => ocrShas(await listChunks(request, token, datasetId, docId)), {
      timeout: POLL_TIMEOUT_MS,
    })
    .toHaveLength(3)
})
