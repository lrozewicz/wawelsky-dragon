// Scenariusze SC-E6-1b-05…07 (SCENARIOS.md WP E6-1b; CONTRACT WP E6-1b §1, §4, §5): filtr
// metadanych w czacie (Ustawienia → Asystent → „Zaawansowane" → „Filtr metadanych"), teście
// retrievalu (rozwijana sekcja) i wyszukiwarce (ustawienia → „Zaawansowane"). Dane buduje API
// (CONTRACT §5): dataset z polami `rok`/`typ` i `enable_metadata`, upload fixture'a z liniami
// `klucz: wartość` + `sample.pdf` + `sample.docx`, parsowanie do DONE (fake-llm `gen_metadata`
// nadaje fixture'owi rok/typ), PATCH `meta_fields` PDF (DOCX celowo bez metadanych).
//
// Testy są CZERWONE przed implementacją (T1b): padają na braku sekcji „Filtr metadanych"
// w UI, nie na setupie — backend E6-1a obsługuje `meta_data_filter` w czacie, retrievalu
// i wyszukiwarce (bieg weryfikacyjny 2026-10-13: filtr typ=ustawa → 0 wyników; pytanie
// z „2023" w trybie auto → cytat tylko z fixture'a; bez filtra Wawel trafia i w PDF,
// i w DOCX, więc asercje „bez sample.docx" są rzeczywistym dyskryminatorem).
// Odchyłka od SC-05 krok 3 (do raportu TL): sample.pdf i sample.docx mają IDENTYCZNĄ treść
// (e2e/README.md, jedno źródło akapitów), więc „treść występująca tylko w DOCX" na stosie
// testowym nie istnieje — pustą odpowiedź weryfikuje pytanie bez wspólnych tokenów,
// a wykluczenie DOCX brak jego nazwy w odpowiedzi przy pytaniu o treść Wawelu.
// Wzorce: s17-dataset-reconfig.spec.ts (sesja, sprzątanie, warianty), s07/s16c (czat),
// s05 (retrieval), s12 (wyszukiwarka).
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import type { APIRequestContext, APIResponse, Locator, Page } from '@playwright/test'

import { expect, test } from './fixtures'
import { POLL_TIMEOUT_MS, apiLogin, createChat, createDataset, deleteAllChats } from './helpers'
import { deleteDataset } from './helpers/files'
import { expectNoLayoutDefects } from './helpers/layout'
import { setProfileLanguage } from './helpers/models'
import { askQuestion, openRetrievalTab } from './helpers/retrieval'
import { deleteAllSearches } from './helpers/searches'
import { uiSession } from './helpers/session'

const API_URL = process.env.WD_E2E_API_URL ?? ''
const FIXTURES = './fixtures'
const FIXTURE_PATH = fileURLToPath(new URL(`${FIXTURES}/metadata-rok-typ.txt`, import.meta.url))
const SAMPLE_PDF_PATH = fileURLToPath(new URL(`${FIXTURES}/sample.pdf`, import.meta.url))
const SAMPLE_DOCX_PATH = fileURLToPath(new URL(`${FIXTURES}/sample.docx`, import.meta.url))
/** MIME DOCX (jak SAMPLE_MIME w helpers/h9.ts). */
const DOCX_MIME = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'

const DATASET_NAME = 'E2E S25 baza z metadanymi'
const PLAIN_DATASET_NAME = 'E2E S25 baza bez metadanych'
const FIXTURE_NAME = 'metadata-rok-typ.txt'
const PDF_NAME = 'sample.pdf'
const DOCX_NAME = 'sample.docx'

/** Tekst „Odpowiedzi przy braku wyników" ustawiany przy tworzeniu czatów przez API (jak S16c). */
const EMPTY_TEXT = 'Brak informacji w bazie'
// Pytania dobrane do treści próbek (e2e/README.md): PDF/DOCX — zamek na Wawelu, fixture —
// raporty o środowisku z 2023. Pytanie „podatkowe" nie ma wspólnych tokenów z korpusuem
// (deterministyczne 0 trafień — pełny tekst 0, wektor fake-embed ~0 × waga 0.3).
const WAWEL_QUESTION = 'Co można oglądać w komnatach zamku na Wawelu?'
const TAX_QUESTION = 'Kiedy mija termin składania deklaracji podatkowej?'
/** Pytanie trybu automatycznego: liczba „2023" → warunek `rok = 2023` z fake-llm (K10). */
const AUTO_QUESTION = 'Co opisują dokumenty z 2023 roku?'

const MODE_GROUP = 'Tryb filtra metadanych'
const FILTER_SECTION = 'Filtr metadanych'
/** Limit na wynik retrievalu / odpowiedź czatu (liczą się dłużej niż domyślne 5 s). */
const ANSWER_TIMEOUT_MS = 45_000

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

/** `meta_fields` dokumentu z listy datasetu (sanity setupu — czerwień ma padać na UI). */
async function documentMeta(
  request: APIRequestContext,
  token: string,
  datasetId: string,
  documentId: string,
): Promise<Record<string, unknown>> {
  const listed = await ok<{ docs: { meta_fields: Record<string, unknown> }[] }>(
    request.get(`${API_URL}/api/v1/datasets/${datasetId}/documents?id=${documentId}`, {
      headers: { authorization: `Bearer ${token}` },
    }),
    'GET …/documents (meta_fields)',
  )
  return listed.docs[0]?.meta_fields ?? {}
}

/** Wgrywa jeden plik multipart-em i czeka na DONE parsowania (wzór `seedCorpus`/s17). */
async function uploadAndParse(
  request: APIRequestContext,
  token: string,
  datasetId: string,
  name: string,
  mimeType: string,
  file: { path?: string; body?: string },
): Promise<string> {
  const headers = { authorization: `Bearer ${token}` }
  const uploaded = await ok<{ id: string }[]>(
    request.post(`${API_URL}/api/v1/datasets/${datasetId}/documents`, {
      headers,
      multipart: {
        file: {
          name,
          mimeType,
          buffer:
            file.path !== undefined
              ? readFileSync(file.path)
              : Buffer.from(file.body ?? '', 'utf-8'),
        },
      },
    }),
    `POST …/documents (${name})`,
  )
  expect(uploaded, `upload ${name} zwrócił dokładnie jeden dokument`).toHaveLength(1)
  const documentId = uploaded[0]!.id
  await ok<unknown>(
    request.post(`${API_URL}/api/v1/datasets/${datasetId}/documents/parse`, {
      headers,
      data: { document_ids: [documentId] },
    }),
    `POST …/documents/parse (${name})`,
  )
  const deadline = Date.now() + POLL_TIMEOUT_MS
  let run = ''
  while (Date.now() < deadline) {
    const listed = await ok<{ docs: { run: string }[] }>(
      request.get(`${API_URL}/api/v1/datasets/${datasetId}/documents?id=${documentId}`, {
        headers,
      }),
      `GET …/documents (poll ${name})`,
    )
    run = listed.docs[0]?.run ?? ''
    if (run === 'DONE' || run === 'FAIL' || run === 'CANCEL') break
    await sleep(1_000)
  }
  expect(run, `stan parsowania ${name}`).toBe('DONE')
  return documentId
}

/**
 * Dataset „z SC-04" (CONTRACT §5): pola `rok` (bez enum) i `typ` (enum raport/rocznik/ustawa),
 * przełącznik `enable_metadata`, fixture + PDF + DOCX sparsowane z auto-metadanymi, PATCH PDF
 * `meta_fields: {typ: 'raport'}` (DOCX zostaje bez metadanych — nie pasuje do żadnego warunku).
 */
async function seedMetadataDataset(request: APIRequestContext, token: string): Promise<string> {
  const headers = { authorization: `Bearer ${token}` }
  const datasetId = await createDataset(request, token, DATASET_NAME)
  await ok<unknown>(
    request.put(`${API_URL}/api/v1/datasets/${datasetId}/metadata/config`, {
      headers,
      data: {
        metadata: [
          { key: 'rok', type: 'string', description: 'Rok, którego dotyczą dane', enum: null },
          {
            key: 'typ',
            type: 'string',
            description: 'Rodzaj dokumentu',
            enum: ['raport', 'rocznik', 'ustawa'],
          },
        ],
      },
    }),
    'PUT …/metadata/config',
  )
  // Przełącznik zwykłym PUT datasetu (CONTRACT §1); backend scala `parser_config` głęboko.
  await ok<unknown>(
    request.put(`${API_URL}/api/v1/datasets/${datasetId}`, {
      headers,
      data: { parser_config: { enable_metadata: true } },
    }),
    'PUT /datasets/{id} (enable_metadata)',
  )
  const fixtureId = await uploadAndParse(request, token, datasetId, FIXTURE_NAME, 'text/plain', {
    path: FIXTURE_PATH,
  })
  const pdfId = await uploadAndParse(request, token, datasetId, PDF_NAME, 'application/pdf', {
    path: SAMPLE_PDF_PATH,
  })
  await uploadAndParse(request, token, datasetId, DOCX_NAME, DOCX_MIME, { path: SAMPLE_DOCX_PATH })
  // Sanity danych: fixture dostaje metadane od fake-llm (`gen_metadata` czyta `klucz: wartość`),
  // PDF bez metadanych — dopiero PATCH nadaje typ=raport (jak ręczna edycja w szufladzie SC-03).
  expect(
    await documentMeta(request, token, datasetId, fixtureId),
    'auto-metadane fixture (rok/typ z fake-llm)',
  ).toEqual({ rok: '2023', typ: 'raport' })
  await ok<unknown>(
    request.patch(`${API_URL}/api/v1/datasets/${datasetId}/documents/${pdfId}`, {
      headers,
      data: { meta_fields: { typ: 'raport' } },
    }),
    'PATCH …/documents/{id} (meta_fields PDF)',
  )
  expect(await documentMeta(request, token, datasetId, pdfId), 'metadane PDF po PATCH').toEqual({
    typ: 'raport',
  })
  return datasetId
}

/** Dataset bez żadnej konfiguracji metadanych (SC-05 krok 7); jeden sparsowany dokument —
 * `POST /chats` odrzuca bazy bez chunków (`chat_validation.py`). */
async function seedPlainDataset(request: APIRequestContext, token: string): Promise<string> {
  const datasetId = await createDataset(request, token, PLAIN_DATASET_NAME)
  await uploadAndParse(request, token, datasetId, 'e2e-s25-pogoda.txt', 'text/plain', {
    body:
      'Prognoza pogody na najbliższy tydzień przewiduje opady deszczu i silny wiatr w całym kraju. ' +
      'Meteorolodzy ostrzegają przed burzami i zalecają pozostanie w domach.',
  })
  return datasetId
}

type Seeded = { token: string; datasetId: string; plainDatasetId: string }

// Wsiew wspólny dla całego pliku (parsowanie 4 dokumentów to dziesiątki sekund); reset K9
// biegnie raz, w `global-setup.ts`, więc dane kolejnych testów są nietknięte (wzór s07/s12).
let shared: Promise<Seeded> | undefined

function seeded(request: APIRequestContext): Promise<Seeded> {
  shared ??= (async () => {
    const token = await apiLogin(request)
    const datasetId = await seedMetadataDataset(request, token)
    const plainDatasetId = await seedPlainDataset(request, token)
    return { token, datasetId, plainDatasetId }
  })()
  return shared
}

// Scenariusze zostawiają po sobie czaty i wyszukiwarki (listy w s07a/s12 zaczynają od pustych
// stanów), a datasety linkują dokumenty — sprzątamy wszystko po biegu pliku.
test.afterAll(async ({ request }) => {
  if (shared === undefined) return
  const { token, datasetId, plainDatasetId } = await shared
  await deleteAllChats(request, token)
  await deleteAllSearches(request, token)
  await deleteDataset(request, token, datasetId)
  await deleteDataset(request, token, plainDatasetId)
})

// Logowanie raz na plik przez API (limiter logowań 10/min współdzielony z biegiem — T11/T14).
const session = uiSession('s25-metadata-filter')
test.use({ storageState: session.statePath })
test.beforeAll(async ({ browser }) => {
  await session.login(browser)
})
test.afterEach(async ({ context }) => {
  await session.save(context)
})

/** Rozwija akordeon „Zaawansowane" (klik tylko, gdy zwinięty — jak „Myślenie…" w S6-07). */
async function expandAdvanced(page: Page, label = 'Zaawansowane'): Promise<void> {
  const summary = page.getByRole('button', { name: label })
  if ((await summary.getAttribute('aria-expanded')) === 'false') await summary.click()
}

/** Szuflada ustawień czatu: zakładka „Asystent", rozwinięte „Zaawansowane". */
async function openChatAssistantAdvanced(
  page: Page,
  advancedLabel = 'Zaawansowane',
): Promise<void> {
  await page.getByRole('button', { name: 'Ustawienia czatu' }).click()
  await page.getByRole('tab', { name: 'Asystent' }).click()
  await expandAdvanced(page, advancedLabel)
}

/** Klik tytułu sekcji filtra: rozwija, gdy kreator jest zwijany; przy zwykłym tytule nic nie psuje. */
async function openFilterSection(page: Page, title = FILTER_SECTION): Promise<void> {
  await page.getByText(title, { exact: true }).click()
}

/** Wypełnia warunek kreatora: Klucz i Operator z list, Wartość z listy albo wpisem własnym. */
async function setCondition(
  page: Page,
  group: Locator,
  key: string,
  op: string,
  value: string,
): Promise<void> {
  await group.getByRole('combobox', { name: 'Klucz' }).click()
  await page.getByRole('option', { name: key, exact: true }).click()
  await group.getByRole('combobox', { name: 'Operator' }).click()
  await page.getByRole('option', { name: op, exact: true }).click()
  await fillConditionValue(page, group, value)
}

/**
 * Wartość warunku: przy operatorze =/≠ i ≤ 20 znanych wartościach kontrolka jest listą
 * (CONTRACT §4) — klikamy opcję; wartości nieobecnej w dokumentach (np. `ustawa`, SC-06
 * krok 2) użytkownik szuka wpisem własnym — piszemy i commitujemy Enterem.
 */
async function fillConditionValue(page: Page, group: Locator, value: string): Promise<void> {
  const valueBox = group.getByRole('combobox', { name: 'Wartość' })
  await valueBox.click()
  const option = page.getByRole('option', { name: value, exact: true })
  if ((await option.count()) > 0) {
    await option.click()
  } else {
    await page.keyboard.type(value)
    await page.keyboard.press('Enter')
  }
}

/** Czat z niepustym „Odpowiedzi przy braku wyników" (jak S16c, próg domyślny). */
async function createEmptyResponseChat(
  request: APIRequestContext,
  token: string,
  datasetId: string,
): Promise<string> {
  const chat = await ok<{ id: string }>(
    request.post(`${API_URL}/api/v1/chats`, {
      headers: { authorization: `Bearer ${token}` },
      data: {
        name: 'E2E S25 czat z filtrem',
        dataset_ids: [datasetId],
        prompt_config: { empty_response: EMPTY_TEXT, refine_multiturn: false },
      },
    }),
    'POST /api/v1/chats',
  )
  return chat.id
}

/** Wpisuje pytanie w czacie i wysyła je przyciskiem (wzór S16c). */
async function ask(page: Page, question: string): Promise<void> {
  await page.getByPlaceholder('Wpisz pytanie…').fill(question)
  await page.getByRole('button', { name: 'Wyślij' }).click()
}

test('SC-E6-1b-05 kroki 1–6: filtr metadanych czatu — zapis warunku, empty_response, cytaty, tryby', async ({
  page,
  request,
}) => {
  // Parsowanie 4 dokumentów w wsiewie + odpowiedzi czatu — zapas ponad domyślne 30 s.
  test.setTimeout(300_000)
  const { token, datasetId } = await seeded(request)
  const chatId = await createEmptyResponseChat(request, token, datasetId)

  await page.goto(`/chat/${chatId}`)

  // Krok 1: Ustawienia → Asystent → „Zaawansowane" → sekcja „Filtr metadanych" z trybami;
  // świeży czat ma `{}` — zaznaczony „Wyłączony" (CONTRACT §4: filterFromWire).
  await openChatAssistantAdvanced(page)
  await openFilterSection(page)
  const modes = page.getByRole('radiogroup', { name: MODE_GROUP })
  await expect(modes).toBeVisible()
  await expect(modes.getByRole('radio', { name: 'Wyłączony' })).toBeChecked()

  // Krok 2: „Ręczny", warunek `typ` `=` `raport`, „Zapisz"; po ponownym otwarciu tryb zachowany.
  await modes.getByRole('radio', { name: 'Ręczny' }).check()
  await setCondition(page, page.getByRole('group', { name: 'Warunek 1' }), 'typ', '=', 'raport')
  await expectNoLayoutDefects(page, 'kreator filtra w szufladzie czatu (SC-05 krok 2)')
  await page.getByRole('button', { name: 'Zapisz' }).click()
  await expect(page.getByRole('tab', { name: 'Asystent' })).toBeHidden()

  await openChatAssistantAdvanced(page)
  await openFilterSection(page)
  await expect(modes.getByRole('radio', { name: 'Ręczny' })).toBeChecked()
  await expect(page.getByRole('group', { name: 'Warunek 1' })).toBeVisible()
  await page.getByRole('button', { name: 'Anuluj' }).click()

  // Krok 3 (odchyłka: PDF i DOCX mają identyczną treść, patrz nagłówek pliku): pytanie bez
  // wspólnych tokenów z korpusu przy aktywnym filtrze → „Odpowiedź przy braku wyników",
  // bez błędu i bez cytatu z DOCX.
  await ask(page, TAX_QUESTION)
  const emptyAnswer = page.getByTestId('message-assistant').last()
  await expect(emptyAnswer).toContainText(EMPTY_TEXT, { timeout: ANSWER_TIMEOUT_MS })
  await expect(emptyAnswer).not.toContainText(DOCX_NAME)
  await expect(emptyAnswer.getByRole('button', { name: 'Cytowanie 1' })).toHaveCount(0)

  // Krok 4: pytanie o treść PDF → odpowiedź z cytatami wyłącznie z sample.pdf (fixture ma inną
  // treść; DOCX bez metadanych nie przechodzi warunku `typ = raport`).
  await ask(page, WAWEL_QUESTION)
  const wawelAnswer = page.getByTestId('message-assistant').last()
  await expect(wawelAnswer).toContainText('Na podstawie źródeł', { timeout: ANSWER_TIMEOUT_MS })
  await expect(wawelAnswer).not.toContainText(DOCX_NAME)
  const chip = wawelAnswer.getByRole('button', { name: 'Cytowanie 1' })
  await expect(chip).toBeVisible()
  await chip.click()
  const citeDialog = page.getByRole('dialog').filter({ has: page.getByTestId('cite-content') })
  await expect(citeDialog).toContainText(PDF_NAME)
  await expect(citeDialog).not.toContainText(DOCX_NAME)
  // Podgląd cytatu otwiera właściwy plik (szuflada podglądu dokumentu, jak S6-07 krok 8).
  await citeDialog.getByRole('button', { name: 'Otwórz dokument' }).click()
  await expect(citeDialog).toBeHidden()
  const preview = page.getByRole('dialog')
  await expect(preview).toContainText(PDF_NAME)
  await page.keyboard.press('Escape')
  await expect(preview).toBeHidden()

  // Krok 5: „Automatyczny" — podpowiedź o dodatkowym wywołaniu modelu; pytanie z „2023"
  // (fake-llm `gen_meta_filter` buduje warunek z liczby w pytaniu) → cytat tylko z fixture'a.
  await openChatAssistantAdvanced(page)
  await openFilterSection(page)
  // exact: substring dopasowałby też „Półautomatyczny" (strict mode violation).
  await modes.getByRole('radio', { name: 'Automatyczny', exact: true }).check()
  await expect(page.getByText('Model sam ułoży filtr z pytania')).toBeVisible()
  await page.getByRole('button', { name: 'Zapisz' }).click()
  await expect(page.getByRole('tab', { name: 'Asystent' })).toBeHidden()
  await ask(page, AUTO_QUESTION)
  const autoAnswer = page.getByTestId('message-assistant').last()
  await expect(autoAnswer).toContainText('Na podstawie źródeł', { timeout: ANSWER_TIMEOUT_MS })
  await expect(autoAnswer).toContainText(FIXTURE_NAME)
  await expect(autoAnswer).not.toContainText(PDF_NAME)
  await expect(autoAnswer).not.toContainText(DOCX_NAME)

  // Krok 6: „Półautomatyczny" — klucz `rok` chipem; zapis i ponowne otwarcie zachowują chip.
  await openChatAssistantAdvanced(page)
  await openFilterSection(page)
  await modes.getByRole('radio', { name: 'Półautomatyczny' }).check()
  await expect(page.getByText('Klucze, po których model może filtrować')).toBeVisible()
  await page.getByRole('combobox', { name: 'Dodaj klucz' }).click()
  await page.getByRole('option', { name: 'rok', exact: true }).click()
  // exact: po naprawie T5b chip jest przyciskiem-ikoną o nazwie „Usuń klucz rok”, a sam chip
  // (role button, nazwa „rok Usuń klucz rok”) też zawiera ten tekst — bez `exact` strict mode.
  await expect(page.getByRole('button', { name: 'Usuń klucz rok', exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Zapisz' }).click()
  await expect(page.getByRole('tab', { name: 'Asystent' })).toBeHidden()
  await openChatAssistantAdvanced(page)
  await openFilterSection(page)
  await expect(page.getByRole('button', { name: 'Usuń klucz rok', exact: true })).toBeVisible()
})

test('SC-E6-1b-05 krok 7: dataset bez metadanych — komunikat z linkiem do konfiguracji', async ({
  page,
  request,
}) => {
  test.setTimeout(120_000)
  const { token, plainDatasetId } = await seeded(request)
  const chatId = await createChat(request, token, {
    name: 'E2E S25 czat bez metadanych',
    datasetIds: [plainDatasetId],
  })

  await page.goto(`/chat/${chatId}`)
  await openChatAssistantAdvanced(page)
  await openFilterSection(page)
  // Baza nie ma metadanych (`hasAny === false`): komunikat zamiast kreatora, z linkiem
  // do konfiguracji datasetu (trasy sprawdzone w `routes/`: /dataset/configuration/:id).
  await expect(page.getByText('Bazy nie mają metadanych')).toBeVisible()
  const link = page.getByRole('link', { name: 'Konfiguracji datasetu' })
  await expect(link).toBeVisible()
  await expect(link).toHaveAttribute('href', new RegExp(`/dataset/configuration/${plainDatasetId}`))
  await expectNoLayoutDefects(page, 'komunikat braku metadanych w szufladzie czatu (SC-05 krok 7)')
})

test('SC-E6-1b-06 kroki 1–2: filtr metadanych w teście retrievalu', async ({ page, request }) => {
  test.setTimeout(240_000)
  const { datasetId } = await seeded(request)

  await openRetrievalTab(page, datasetId)
  await expandAdvanced(page)
  await openFilterSection(page)
  const modes = page.getByRole('radiogroup', { name: MODE_GROUP })
  await expect(modes).toBeVisible()
  // Test retrievalu obsługuje tylko tryby Wyłączony/Ręczny (CONTRACT §4) — auto/semi_auto
  // niedostępne.
  // exact: „Automatyczny" substringem trafia też w „Półautomatyczny" (strict mode violation).
  await expect(modes.getByRole('radio', { name: 'Automatyczny', exact: true })).toBeDisabled()
  await expect(modes.getByRole('radio', { name: 'Półautomatyczny', exact: true })).toBeDisabled()

  // Krok 1: warunek `typ = raport`, pytanie o treść PDF → wyniki tylko z sample.pdf (bez filtra
  // trafiają i PDF, i DOCX — bieg weryfikacyjny 2026-10-13; warunek usuwa DOCX z zakresu).
  await modes.getByRole('radio', { name: 'Ręczny' }).check()
  const warunek = page.getByRole('group', { name: 'Warunek 1' })
  await setCondition(page, warunek, 'typ', '=', 'raport')
  await askQuestion(page, WAWEL_QUESTION)
  const results = page.getByTestId('retrieval-result')
  await expect(results.first()).toBeVisible({ timeout: ANSWER_TIMEOUT_MS })
  await expect(results.first()).toContainText(PDF_NAME)
  await expect(results.filter({ hasText: DOCX_NAME })).toHaveCount(0)
  await expectNoLayoutDefects(page, 'wyniki retrievalu z filtrem metadanych (SC-06 krok 1)')

  // Krok 2: warunek bez dopasowań (`typ = ustawa` — wpis własny, żaden dokument nie ma tej
  // wartości) → komunikat wykluczenia, nie ogólne „Nie znaleziono".
  await fillConditionValue(page, warunek, 'ustawa')
  await askQuestion(page, WAWEL_QUESTION)
  await expect(
    page.getByText('Filtr metadanych wykluczył wszystkie dokumenty'),
    'komunikat wykluczenia zamiast ogólnego pustego stanu',
  ).toBeVisible({ timeout: ANSWER_TIMEOUT_MS })
  await expect(results).toHaveCount(0)
  await expectNoLayoutDefects(page, 'komunikat wykluczenia w teście retrievalu (SC-06 krok 2)')
})

test('SC-E6-1b-07 kroki 1–2: filtr metadanych w ustawieniach wyszukiwarki', async ({
  page,
  request,
}) => {
  test.setTimeout(240_000)
  const { token } = await seeded(request)
  // Wyszukiwarkę tworzymy przez API (odporne na ponowienia — przycisk „Utwórz wyszukiwarkę"
  // żyje tylko w pustym stanie listy, jak S6-12 krok 2); filtr ustawia już UI.
  const created = await ok<{ search_id: string }>(
    request.post(`${API_URL}/api/v1/searches`, {
      headers: { authorization: `Bearer ${token}` },
      data: { name: 'E2E S25 wyszukiwarka', description: '' },
    }),
    'POST /api/v1/searches',
  )
  await page.goto(`/search/${created.search_id}`)
  // Świeża wyszukiwarka bez baz sama otwiera szufladę ustawień (kontrakt §4, jak S6-12 krok 3).
  await expect(page.getByRole('heading', { name: 'Ustawienia wyszukiwarki' })).toBeVisible()
  await page.getByRole('combobox', { name: 'Bazy wiedzy' }).click()
  await page.getByRole('option', { name: DATASET_NAME }).click()

  // Krok 1: „Zaawansowane" → „Filtr metadanych", tryb Ręczny, warunek `typ = raport`, zapis;
  // po ponownym otwarciu warunek zachowany.
  await expandAdvanced(page)
  await openFilterSection(page)
  const modes = page.getByRole('radiogroup', { name: MODE_GROUP })
  await expect(modes).toBeVisible()
  await modes.getByRole('radio', { name: 'Ręczny' }).check()
  await setCondition(page, page.getByRole('group', { name: 'Warunek 1' }), 'typ', '=', 'raport')
  await expectNoLayoutDefects(page, 'kreator filtra w szufladzie wyszukiwarki (SC-07 krok 1)')
  await page.getByRole('button', { name: 'Zapisz' }).click()
  await expect(page.getByRole('button', { name: 'Zapisz' })).toBeHidden()
  await page.getByRole('button', { name: 'Otwórz ustawienia wyszukiwarki' }).click()
  await expandAdvanced(page)
  await openFilterSection(page)
  await expect(modes.getByRole('radio', { name: 'Ręczny' })).toBeChecked()
  await expect(page.getByRole('group', { name: 'Warunek 1' })).toBeVisible()
  await page.getByRole('button', { name: 'Zamknij ustawienia' }).click()

  // Krok 2 (odchyłka treści jak w SC-05 krok 3): fraza z treści DOCX/PDF przy filtrze —
  // trafienia bez sample.docx, stan z wynikami z PDF, bez błędu.
  await page.getByLabel('Pytanie').fill(WAWEL_QUESTION)
  await page.getByRole('button', { name: 'Wyślij' }).click()
  const hit = page.getByTestId('search-hit').first()
  await expect(hit).toBeVisible({ timeout: ANSWER_TIMEOUT_MS })
  await expect(hit).toContainText(PDF_NAME)
  await expect(page.getByTestId('search-hit').filter({ hasText: DOCX_NAME })).toHaveCount(0)
  await expectNoLayoutDefects(page, 'wyniki wyszukiwarki z filtrem metadanych (SC-07 krok 2)')
})

test.describe('SC-E6-1b-05 warianty wyglądu i języka', () => {
  test.describe('390 px + ciemny motyw', () => {
    test.use({ viewport: { width: 390, height: 844 }, colorScheme: 'dark' })

    test('kreator filtra w szufladzie ustawień czatu mieści się w ekranie', async ({
      page,
      request,
    }) => {
      test.setTimeout(120_000)
      const { token, datasetId } = await seeded(request)
      const chatId = await createChat(request, token, {
        name: 'E2E S25 czat wariant',
        datasetIds: [datasetId],
      })

      await page.goto(`/chat/${chatId}`)
      await openChatAssistantAdvanced(page)
      await openFilterSection(page)
      await expect(page.getByRole('radiogroup', { name: MODE_GROUP })).toBeVisible()
      await page.getByRole('radio', { name: 'Ręczny' }).check()
      await setCondition(page, page.getByRole('group', { name: 'Warunek 1' }), 'typ', '=', 'raport')
      await expectNoLayoutDefects(page, 'kreator filtra metadanych 390 px w ciemnym motywie')
    })
  })

  test('wariant EN: sekcja „Metadata filter" i tryby', async ({ page, request }) => {
    test.setTimeout(120_000)
    // Profil admina nadpisuje locale przeglądarki po zalogowaniu (authState.applyUser).
    const { token, datasetId } = await seeded(request)
    await setProfileLanguage(request, token, 'en')
    const chatId = await createChat(request, token, {
      name: 'E2E S25 czat EN',
      datasetIds: [datasetId],
    })

    await page.goto(`/chat/${chatId}`)
    // Po zmianie języka profilu cała szuflada mówi po EN (chat.settings.*), więc otwieramy
    // ją etykietami EN — wariant sprawdza właśnie te teksty.
    await page.getByRole('button', { name: 'Chat settings' }).click()
    await page.getByRole('tab', { name: 'Assistant' }).click()
    await expandAdvanced(page, 'Advanced')
    await openFilterSection(page, 'Metadata filter')
    // EN minimum (CONTRACT §4): tytuł sekcji i nazwy trybów.
    await expect(page.getByRole('radio', { name: 'Off' })).toBeVisible()
    await expect(page.getByRole('radio', { name: 'Manual' })).toBeVisible()
    // exact: „Automatic" substringem trafia też w „Semi-automatic" (strict mode violation).
    await expect(page.getByRole('radio', { name: 'Automatic', exact: true })).toBeVisible()
    await expect(page.getByRole('radio', { name: 'Semi-automatic', exact: true })).toBeVisible()
    await expectNoLayoutDefects(page, 'kreator filtra metadanych (EN)')
  })
})

// Wariant EN zmienia język profilu — przywracamy PL, żeby kolejne pliki biegu widziały PL
// (wzór s17-dataset-reconfig.spec.ts).
test.afterEach(async ({ request }) => {
  if (shared === undefined) return
  const { token } = await shared
  await setProfileLanguage(request, token, 'pl')
})
