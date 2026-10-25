// Scenariusze SC-E6-1b-01 (krok z uploadem), SC-E6-1b-04 i SC-E6-1b-05 (kroki 1–4) w UI na
// produkcyjnym stosie clean-install z fake-llm (SCENARIOS.md WP E6-1b, brief T1c) — R-ING-09
// zamknięty „oczami użytkownika" na stosie prod. Bieg:
//   WD_CI_SPEC=real-metadata-ui.spec.ts flock /tmp/wd-verify-real.lock tools/dev/clean-install.sh
// Konwencja e2e-real: bez seedu K9 i bez `POST /api/wd/v1/test/reset`; selektory „jak
// użytkownik" (role/etykiety/tekst, bez `data-testid`), dane pomocnicze przez API kontem
// administratora czystej instalacji (WD_CI_ADMIN_*); login formularzem (wzór: real-corpus.spec.ts).
// Przebieg (serial, jak real-metadata.spec.ts): SC-01 tworzy w UI dataset z polami `rok`/`typ`
// (sekcja „Metadane"), wgrywa fixture prawdziwym przeciągnięciem i czeka na chipy w kolumnie
// „Metadane" (od xl, ≥ 1536 px — viewport 1600); SC-04 dosyła przez API notatkę pogodową BEZ
// słów z pól metadanych (fake-llm deterministycznie: enum = słowo z treści, pole bez enum =
// linia `klucz: wartość` — fake_llm/metadata.py; notatka dostaje {} — patrz tools/fake-llm),
// więc filtr `typ = raport` na liście ma realny dyskryminator; SC-05 ustawia filtr ręczny
// czatu w Ustawieniach (Asystent → „Zaawansowane") i pyta o treść notatki (poza raportami →
// `empty_response`) oraz o treść fixture'a (cytat z fixture'a).
// Fixture metadanych: `fixtures/metadata-rok-typ.txt` (linie `rok: 2023`, `typ: raport` — ten
// sam co SC-E6-1a-01). Pytania = dosłowne zdania treści dokumentów (fake-embed deterministyczny).
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

import { expect, test } from '@playwright/test'
import type { APIRequestContext, APIResponse, Page } from '@playwright/test'

import { dropFile } from './helpers/dnd'

const ADMIN_EMAIL = process.env.WD_CI_ADMIN_EMAIL ?? ''
const ADMIN_PASSWORD = process.env.WD_CI_ADMIN_PASSWORD ?? ''

const DATASET_NAME = 'real-metadata-ui-ds'
const FIXTURE_NAME = 'metadata-rok-typ.txt'
const FIXTURE_PATH = fileURLToPath(new URL('./fixtures/metadata-rok-typ.txt', import.meta.url))
const FIXTURE_MIME = 'text/plain'
// Notatka pogodowa (SC-04/SC-05): celowo BEZ słów `raport`/`rocznik`/`ustawa` i bez linii
// `klucz: wartość` — auto-metadane fake-llm dają {}, więc nie przechodzi filtra `typ = raport`.
const NOTES_NAME = 'notatka-pogoda.txt'
const NOTES_BODY =
  'Prognoza pogody na najbliższy tydzień przewiduje opady deszczu i silny wiatr w całym kraju. ' +
  'Meteorolodzy ostrzegają przed burzami i zalecają pozostanie w domach.\n'
// Pytanie „poza raportami": dosłowny fragment notatki — bez filtra trafiłoby w notatkę,
// z filtrem `typ = raport` notatka jest wykluczona → empty_response (realny dyskryminator).
const NOTES_QUESTION =
  'Prognoza pogody na najbliższy tydzień przewiduje opady deszczu i silny wiatr?'
// Pytanie z fixture'a: pierwsze zdanie treści (wzór: real-metadata.spec.ts SC-04).
const FIXTURE_QUESTION = 'Raporty z 2023 roku opisują stan środowiska w Polsce.'
// „Odpowiedzi przy braku wyników" czatu tworzonego przez API (wzór: s25-metadata-filter).
const EMPTY_TEXT = 'Brak informacji w bazie'
// Prefiks odpowiedzi fake-chat, gdy retrieval dał fragmenty (K10 §4).
const SOURCES_PREFIX = 'Na podstawie źródeł: '

// Kolumna „Metadane" jest od xl (≥ 1536 px, CONTRACT WP E6-1b §4) — asercje chipów biegną przy 1600 px.
const WIDE_VIEWPORT = { width: 1600, height: 900 }
// Parsowanie małych plików tekstowych na stosie prod. — poll co 3 s (limit z zapasą).
const PARSE_TIMEOUT_MS = 240_000
const POLL_INTERVAL_MS = 3_000
// Wiersz siatki pojawia się po uploadzie w rytmie odświeżania listy (3 s) — limit z zapasą.
const ROW_TIMEOUT_MS = 60_000
// Odpowiedź czatu (fake-chat) — limity jak real-corpus.spec.ts.
const ANSWER_TIMEOUT_MS = 60_000

// Budżet SCENARIOS.md: chipy w kolumnie „Metadane" ≤ 5 s po „Sukces", bez ręcznego odświeżania.
const CHIP_TIMEOUT_MS = 5_000

type Envelope<T> = { code: number; message?: string; data?: T }

/** Rozwija kopertę RAGFlow: HTTP 200 + `code 0`, inaczej wyjątek (wzór: real-metadata.spec.ts). */
async function ok<T>(response: APIResponse, label: string): Promise<T> {
  const body = (await response.json()) as Envelope<T>
  expect(response.status(), `${label}: HTTP ${response.status()} — ${body.message}`).toBe(200)
  expect(body.code, `${label}: ${body.message}`).toBe(0)
  return body.data as T
}

/** Login administratora; zwraca nagłówek Authorization (sesja, wzór: real-metadata.spec.ts). */
async function apiLogin(request: APIRequestContext): Promise<string> {
  const response = await request.post('/api/v1/auth/login', {
    data: { email: ADMIN_EMAIL, password: ADMIN_PASSWORD },
  })
  await ok<unknown>(response, 'POST /api/v1/auth/login')
  const authorization = response.headers()['authorization']
  expect(authorization, 'login: brak nagłówka Authorization').toBeTruthy()
  return authorization!
}

/** Utworzenie datasetu przez API (dane pomocnicze; pola metadanych konfiguruje UI). */
async function createDataset(
  request: APIRequestContext,
  authorization: string,
  name: string,
): Promise<string> {
  const response = await request.post('/api/v1/datasets', {
    headers: { authorization },
    data: { name },
  })
  const created = await ok<{ id: string }>(response, 'POST /datasets')
  return created.id
}

/** Upload multipart z pamięci (wzór: real-metadata.spec.ts); zwraca id dokumentu. */
async function uploadDoc(
  request: APIRequestContext,
  authorization: string,
  datasetId: string,
  name: string,
  mimeType: string,
  bytes: Buffer,
): Promise<string> {
  const response = await request.post(`/api/v1/datasets/${datasetId}/documents`, {
    headers: { authorization },
    multipart: { file: { name, mimeType, buffer: bytes } },
  })
  const uploaded = await ok<{ id: string }[]>(response, `POST /datasets/{id}/documents (${name})`)
  expect(uploaded.length, `upload ${name}: pusta lista dokumentów`).toBeGreaterThan(0)
  return uploaded[0]!.id
}

/** Zlecenie parsowania (POST …/documents/parse). */
async function parseDocs(
  request: APIRequestContext,
  authorization: string,
  datasetId: string,
  documentIds: string[],
): Promise<void> {
  const response = await request.post(`/api/v1/datasets/${datasetId}/documents/parse`, {
    headers: { authorization },
    data: { document_ids: documentIds },
  })
  await ok<unknown>(response, 'POST /datasets/{id}/documents/parse')
}

/** Poll `run = DONE` dokumentu (wzór: real-metadata.spec.ts); bez zwracanej treści. */
async function awaitDone(
  request: APIRequestContext,
  authorization: string,
  datasetId: string,
  documentId: string,
  timeoutMs: number,
): Promise<void> {
  const label = `poll dokumentu ${documentId}`
  const deadline = Date.now() + timeoutMs
  for (;;) {
    const response = await request.get(`/api/v1/datasets/${datasetId}/documents`, {
      headers: { authorization },
      params: { id: documentId },
    })
    const page = await ok<{ docs: { id: string; run: string }[] }>(
      response,
      'GET /datasets/{id}/documents',
    )
    const run = page.docs.find((row) => row.id === documentId)?.run ?? ''
    if (run === 'DONE') return
    if (run === 'FAIL' || run === 'CANCEL') throw new Error(`${label}: run=${run}`)
    if (Date.now() >= deadline) {
      throw new Error(`${label}: niedokończone po ${timeoutMs / 1000} s (run=${run})`)
    }
    await new Promise((resolve) => setTimeout(resolve, POLL_INTERVAL_MS))
  }
}

/** Czat na datasetcie z własnym „Odpowiedzi przy braku wyników" (wzór: s25-metadata-filter). */
async function createChat(
  request: APIRequestContext,
  authorization: string,
  datasetId: string,
): Promise<string> {
  const response = await request.post('/api/v1/chats', {
    headers: { authorization },
    data: {
      name: `real-metadata-ui-chat-${Date.now()}`,
      dataset_ids: [datasetId],
      prompt_config: { empty_response: EMPTY_TEXT, refine_multiturn: false },
    },
  })
  const chat = await ok<{ id: string }>(response, 'POST /chats')
  return chat.id
}

/** Wypełnia i wysyła formularz logowania na `/login` (wzór: real-corpus.spec.ts). */
async function loginAsAdmin(page: Page): Promise<void> {
  await page.goto('/login')
  await page.getByLabel('E-mail').fill(ADMIN_EMAIL)
  // `exact` — bez niego „Hasło" trafia też w „Pokaż hasło" (wzór: real-corpus.spec.ts).
  await page.getByLabel('Hasło', { exact: true }).fill(ADMIN_PASSWORD)
  await page.getByRole('button', { name: 'Zaloguj się' }).click()
  await expect(
    page.getByRole('navigation').getByRole('link', { name: 'Bazy wiedzy' }),
  ).toBeVisible()
}

/** Rozwija akordeon „Zaawansowane" (klik tylko, gdy zwinięty — wzór: s25-metadata-filter). */
async function expandAdvanced(page: Page): Promise<void> {
  const summary = page.getByRole('button', { name: 'Zaawansowane' })
  if ((await summary.getAttribute('aria-expanded')) === 'false') await summary.click()
}

/** Klik tytułu sekcji filtra metadanych w szufladzie (rozwija, gdy zwinięty). */
async function openFilterSection(page: Page): Promise<void> {
  await page.getByText('Filtr metadanych', { exact: true }).click()
}

/**
 * Upload pliku z dysku dialogiem „Prześlij pliki" — prawdziwe przeciągnięcie na strefę
 * „Przeciągnij pliki tutaj" (bez `data-testid`, wzór: real-corpus.spec.ts) i wysyłka z
 * domyślnie włączonym „Parsuj po przesłaniu".
 */
async function uploadFixtureViaUi(page: Page): Promise<void> {
  await page.getByRole('button', { name: 'Prześlij plik' }).click()
  const uploadDialog = page.getByRole('dialog')
  await expect(uploadDialog.getByRole('heading', { name: 'Prześlij pliki' })).toBeVisible()
  await expect(uploadDialog.getByRole('switch', { name: 'Parsuj po przesłaniu' })).toBeChecked()
  const dropzone = uploadDialog.getByText('Przeciągnij pliki tutaj')
  await dropFile(page, dropzone, readFileSync(FIXTURE_PATH), FIXTURE_NAME, FIXTURE_MIME)
  await expect(uploadDialog.getByText(FIXTURE_NAME, { exact: true })).toBeVisible()
  await uploadDialog.getByRole('button', { name: 'Prześlij' }).click()
  await expect(uploadDialog.getByText('Przesłano', { exact: true })).toBeVisible({
    timeout: ROW_TIMEOUT_MS,
  })
  await uploadDialog.getByRole('button', { name: 'Gotowe' }).click()
  await expect(uploadDialog).toBeHidden()
}

/** Wiersz siatki dokumentu o danej nazwie (`role=row`, wzór: real-corpus.spec.ts). */
function documentRow(page: Page, name: string) {
  return page.getByRole('row').filter({ hasText: name })
}

// Stan serialny: SC-01 przygotowuje dataset, SC-04/SC-05 korzystają (wzór: real-metadata.spec.ts).
test.describe.configure({ mode: 'serial' })

let datasetId = ''

test('SC-E6-1b-01 (real, UI): pola metadanych w sekcji „Metadane", upload fixture, chipy w kolumnie', async ({
  page,
  request,
}) => {
  // Konfiguracja w UI + upload + parsowanie fixture'a — zapas ponad domyślne 300 s niepotrzebny,
  // ale jawny limit dokumentuje budżet (wzór: real-metadata.spec.ts).
  test.setTimeout(300_000)
  await page.setViewportSize(WIDE_VIEWPORT)
  const authorization = await apiLogin(request)
  datasetId = await createDataset(request, authorization, DATASET_NAME)

  // Konfiguracja pól w UI (sekcja „Metadane", CONTRACT WP E6-1b §4): rok bez enum, typ z enum.
  await loginAsAdmin(page)
  await page.goto(`/dataset/configuration/${datasetId}`)
  await expect(page.getByRole('heading', { name: DATASET_NAME })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Metadane' })).toBeVisible()

  await page.getByRole('button', { name: '+ Pole' }).click()
  const row1 = page.getByRole('group', { name: 'Pole 1' })
  await row1.getByLabel('Klucz').fill('rok')
  await row1.getByLabel('Opis').fill('Rok, którego dotyczą dane')
  await page.getByRole('button', { name: '+ Pole' }).click()
  const row2 = page.getByRole('group', { name: 'Pole 2' })
  await row2.getByLabel('Klucz').fill('typ')
  await row2.getByLabel('Opis').fill('Rodzaj dokumentu')
  const values2 = row2.getByLabel('Dozwolona wartość')
  for (const value of ['raport', 'rocznik', 'ustawa']) {
    await values2.fill(value)
    await values2.press('Enter')
  }
  await expect(row2.locator('[aria-label="Usuń wartość raport"]')).toBeVisible()

  const autoSwitch = page.getByRole('switch', { name: 'Auto-metadane' })
  await autoSwitch.click()
  await expect(autoSwitch).toBeChecked()
  await page.getByRole('button', { name: 'Zapisz' }).click()
  await expect(page.getByText('Zapisano')).toBeVisible()
  // Dataset nie ma plików — dialog „Zastosować zmiany…" nie ma prawa się otworzyć (wzór: s25).
  await expect(
    page.getByRole('dialog', { name: 'Zastosować zmiany do istniejących plików?' }),
  ).toHaveCount(0)

  // Upload fixture prawdziwym plikiem (przeciągnięcie); „Parsuj po przesłaniu" parsuje od razu.
  await page.getByRole('tab', { name: 'Pliki' }).click()
  await uploadFixtureViaUi(page)
  const fixtureRow = documentRow(page, FIXTURE_NAME)
  await expect(fixtureRow).toBeVisible({ timeout: ROW_TIMEOUT_MS })
  const statusButton = fixtureRow.getByRole('button', { name: /^(Sukces|Błąd|Anulowano)$/ })
  await expect(statusButton, 'stan parsowania fixture').toHaveText('Sukces', {
    timeout: PARSE_TIMEOUT_MS,
  })

  // Kolumna „Metadane" (od xl) z chipami `rok: 2023`, `typ: raport` — bez odświeżania strony,
  // ≤ 5 s po „Sukces" (budżet SCENARIOS.md; lista odpytuje co 3 s, chipy jadą w tym samym polu).
  await expect(page.getByRole('columnheader', { name: 'Metadane' })).toBeVisible()
  await expect(fixtureRow.getByText('rok: 2023')).toBeVisible({ timeout: CHIP_TIMEOUT_MS })
  await expect(fixtureRow.getByText('typ: raport')).toBeVisible({ timeout: CHIP_TIMEOUT_MS })
})

test('SC-E6-1b-04 (real, UI): filtr metadanych na liście — tylko fixture, chip „1 warunek", ×', async ({
  page,
  request,
}) => {
  test.setTimeout(300_000)
  await page.setViewportSize(WIDE_VIEWPORT)
  const authorization = await apiLogin(request)
  expect(datasetId, 'SC-01 przygotował dataset').not.toBe('')

  // Notatka pogodowa przez API (dane pomocnicze): dziedziczy parser_config z auto-metadanymi
  // przy uploadzie, ale fake-llm nie znajduje słów pól → meta_fields {} — nie przechodzi filtra.
  const notesId = await uploadDoc(
    request,
    authorization,
    datasetId!,
    NOTES_NAME,
    FIXTURE_MIME,
    Buffer.from(NOTES_BODY, 'utf-8'),
  )
  await parseDocs(request, authorization, datasetId!, [notesId])
  await awaitDone(request, authorization, datasetId!, notesId, PARSE_TIMEOUT_MS)

  await loginAsAdmin(page)
  await page.goto(`/dataset/files/${datasetId}`)
  await expect(page.getByRole('heading', { name: DATASET_NAME })).toBeVisible()
  const fixtureRow = documentRow(page, FIXTURE_NAME)
  const notesRow = documentRow(page, NOTES_NAME)
  await expect(fixtureRow).toBeVisible({ timeout: ROW_TIMEOUT_MS })
  await expect(notesRow).toBeVisible({ timeout: ROW_TIMEOUT_MS })
  // Sanity danych: notatka bez metadanych („—" w kolumnie), fixture z chipami.
  await expect(notesRow.getByText('—', { exact: true })).toBeVisible()
  await expect(fixtureRow.getByText('typ: raport')).toBeVisible()

  // Filtr metadanych nad tabelą: kreator, warunek `typ = raport` (wartość podpowiadana z danych).
  await page.getByRole('button', { name: 'Filtr metadanych' }).click({ timeout: 10_000 })
  const warunek1 = page.getByRole('group', { name: 'Warunek 1' })
  await expect(warunek1).toBeVisible()
  await warunek1.getByRole('combobox', { name: 'Klucz' }).click()
  await page.getByRole('option', { name: 'typ', exact: true }).click()
  await warunek1.getByRole('combobox', { name: 'Operator' }).click()
  await page.getByRole('option', { name: '=', exact: true }).click()
  await warunek1.getByRole('combobox', { name: 'Wartość' }).click()
  await page.getByRole('option', { name: 'raport', exact: true }).click()
  await page.getByRole('button', { name: 'Zastosuj' }).click()
  await expect(warunek1).toBeHidden()

  // Chip „Metadane: 1 warunek" z ×; lista: tylko fixture — notatka wypada.
  await expect(page.getByText('Metadane: 1 warunek')).toBeVisible()
  const removeChip = page.locator('[aria-label="Usuń filtr metadanych"]')
  await expect(removeChip).toBeVisible()
  await expect(fixtureRow).toBeVisible()
  await expect(notesRow).toHaveCount(0)

  // × zdejmuje filtr: pełna lista wraca, chip znika.
  await removeChip.click()
  await expect(page.getByText(/^Metadane:/)).toHaveCount(0)
  await expect(fixtureRow).toBeVisible()
  await expect(notesRow).toBeVisible()
})

test('SC-E6-1b-05 (real, UI): czat z ręcznym filtrem metadanych — empty_response i cytat z fixture', async ({
  page,
  request,
}) => {
  test.setTimeout(300_000)
  const authorization = await apiLogin(request)
  expect(datasetId, 'SC-01 przygotował dataset').not.toBe('')
  const chatId = await createChat(request, authorization, datasetId!)

  await loginAsAdmin(page)
  await page.goto(`/chat/${chatId}`)

  // Krok 1–2: Ustawienia czatu → Asystent → „Zaawansowane" → „Filtr metadanych"; świeży czat
  // ma tryb „Wyłączony"; ustawiamy „Ręczny" z warunkiem `typ = raport` i zapisujemy.
  await page.getByRole('button', { name: 'Ustawienia czatu' }).click()
  await page.getByRole('tab', { name: 'Asystent' }).click()
  await expandAdvanced(page)
  await openFilterSection(page)
  const modes = page.getByRole('radiogroup', { name: 'Tryb filtra metadanych' })
  await expect(modes).toBeVisible()
  await expect(modes.getByRole('radio', { name: 'Wyłączony' })).toBeChecked()
  await modes.getByRole('radio', { name: 'Ręczny' }).check()
  const warunek1 = page.getByRole('group', { name: 'Warunek 1' })
  await warunek1.getByRole('combobox', { name: 'Klucz' }).click()
  await page.getByRole('option', { name: 'typ', exact: true }).click()
  await warunek1.getByRole('combobox', { name: 'Operator' }).click()
  await page.getByRole('option', { name: '=', exact: true }).click()
  await warunek1.getByRole('combobox', { name: 'Wartość' }).click()
  await page.getByRole('option', { name: 'raport', exact: true }).click()
  await page.getByRole('button', { name: 'Zapisz' }).click()
  await expect(page.getByRole('tab', { name: 'Asystent' })).toBeHidden()

  // Zapis trwały: po ponownym otwarciu tryb i warunek zachowane (krok 2 SCENARIOS.md).
  await page.getByRole('button', { name: 'Ustawienia czatu' }).click()
  await page.getByRole('tab', { name: 'Asystent' }).click()
  await expandAdvanced(page)
  await openFilterSection(page)
  await expect(modes.getByRole('radio', { name: 'Ręczny' })).toBeChecked()
  await expect(page.getByRole('group', { name: 'Warunek 1' })).toBeVisible()
  await page.getByRole('button', { name: 'Anuluj' }).click()
  await expect(page.getByRole('tab', { name: 'Asystent' })).toBeHidden()

  // Krok 3: pytanie o treść notatki (poza raportami; bez filtra trafiłoby w notatkę) —
  // filtr `typ = raport` wyklucza notatkę → „Odpowiedź przy braku wyników" czatu, bez cytatów.
  await page.getByPlaceholder('Wpisz pytanie…').fill(NOTES_QUESTION)
  await page.getByRole('button', { name: 'Wyślij' }).click()
  const emptyAnswer = page.getByRole('article', { name: 'Odpowiedź asystenta' }).last()
  await expect(emptyAnswer).toContainText(EMPTY_TEXT, { timeout: ANSWER_TIMEOUT_MS })
  await expect(emptyAnswer.getByRole('button', { name: /^Cytowanie \d+$/ })).toHaveCount(0)

  // Krok 4: pytanie z treści fixture'a → odpowiedź z fragmentami, cytat prowadzi do fixture'a.
  await page.getByPlaceholder('Wpisz pytanie…').fill(FIXTURE_QUESTION)
  await page.getByRole('button', { name: 'Wyślij' }).click()
  const hitAnswer = page.getByRole('article', { name: 'Odpowiedź asystenta' }).last()
  await expect(hitAnswer).toContainText(SOURCES_PREFIX, { timeout: ANSWER_TIMEOUT_MS })
  await expect(hitAnswer).toContainText(FIXTURE_NAME)
  const chip = hitAnswer.getByRole('button', { name: 'Cytowanie 1' })
  await expect(chip).toBeVisible()
  await chip.click()
  const citeDialog = page.getByRole('dialog').filter({
    has: page.getByRole('heading', { name: FIXTURE_NAME }),
  })
  await expect(citeDialog).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(citeDialog).toBeHidden()
})
