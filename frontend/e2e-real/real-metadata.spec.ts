// Scenariusze SC-E6-1a-01…07 (SCENARIOS.md WP E6-1a, brief T8a): metadane jak klient SDK —
// testy API Playwright (bez widoków; UI to E6-1b) na produkcyjnym stosie clean-install
// z fake-llm i korpusem PL `WD_REAL_CORPUS`. Bieg:
//   WD_CI_SPEC=real-metadata.spec.ts flock /tmp/wd-verify-real.lock tools/dev/clean-install.sh
// Dane przygotowuje API kontem administratora czystej instalacji (WD_CI_ADMIN_*, konwencja
// e2e-real: bez SQL, bez seedu K9). Atrapa metadanych jest DETERMINISTYCZNA (K10 „Poprawka
// 2026-10-11b"): auto-metadane — enum = pierwsza wartość występująca w treści (granice słów,
// bez wielkości liter), pole bez enum — pierwsza linia `klucz: wartość`; treść to złączone
// teksty chunków obcięte do 16000 znaków. Stąd oczekiwania `meta_fields` są równe dokładnie
// (toEqual). Korpusowy PDF > 100 stron to rocznik GUS — bieg 2026-10-12 pokazał `{}` (w oknie
// 16000 znaków tekstów chunków nie ma wartości enum; log `Auto metadata: 0 fields`), więc
// wszystkie pliki korpusu są „bez dopasowań" i tylko fixture dostaje pola — patrz DEC-301
// (docs/decisions/DEC-301.md, sekcja Obserwacja). Fallback fixture'a `multi-batch-120.pdf`
// z `frontend/e2e/fixtures/` tylko wtedy, gdy korpus nie ma GUS-u (korpus nie jest w gicie).
// Pomiar 10k (SC-06) biega w T6 — tu jawny skip. SC-07: zmiana pól datasetu nie dotyka już
// wgranych dokumentów (K11 §10f p. 4 — dziedziczenie przy uploadzie, część 1 dokumentuje to
// asercją); nowe pola dla istniejącego pliku użytkownik nadaje konfiguracją dokumentu
// (S-320, K11 §10f p. 2) + „Parsuj ponownie" (część 2; decyzja TL 2026-10-12, wariant P1
// wg .task/BLOCKED). Luka UX (zmiana pól datasetu a istniejące pliki) — do Architekta/E6-1b.
import { readFileSync, readdirSync } from 'node:fs'
import { basename, join } from 'node:path'
import { fileURLToPath } from 'node:url'

import { expect, test } from '@playwright/test'
import type { APIRequestContext, APIResponse } from '@playwright/test'

const ADMIN_EMAIL = process.env.WD_CI_ADMIN_EMAIL ?? ''
const ADMIN_PASSWORD = process.env.WD_CI_ADMIN_PASSWORD ?? ''
const CORPUS = process.env.WD_REAL_CORPUS ?? ''

const DATASET_NAME = 'real-metadata-ds'
const FIXTURE_NAME = 'metadata-rok-typ.txt'
const FIXTURE_PATH = fileURLToPath(new URL('./fixtures/metadata-rok-typ.txt', import.meta.url))
const GUS_NAME = 'gus_rocznik_statystyczny_rp_2024.pdf'
// Fallback briefu: gdy korpus nie ma PDF > 100 stron — fixture 120-stronicowy z repo.
const MULTI_BATCH_PATH = fileURLToPath(
  new URL('../e2e/fixtures/multi-batch-120.pdf', import.meta.url),
)
const MULTI_BATCH_NAME = 'multi-batch-120.pdf'

// Pola auto-metadanych datasetu (SCENARIOS.md SC-01: rok string, typ enum).
const FIELDS = [
  { key: 'rok', type: 'string', description: 'Rok, którego dotyczą dane' },
  { key: 'typ', type: 'string', enum: ['raport', 'rocznik', 'ustawa'] },
]

// SC-01 parsuje korpusowy rocznik GUS (745 stron; zmierzone ~581 s na tym stosie) — budżet
// z zapasą; pozostałe testy mieszczą się w domyślnym limicie konfiguracji (300 s).
const BIG_PARSE_TIMEOUT_MS = 1_500_000
const BIG_POLL_TIMEOUT_MS = 1_200_000
const POLL_INTERVAL_MS = 3_000

// Odpowiedź czatu bez trafień filtra (domyślny `empty_response` profilu v0.27; złoto
// metadata_e6--50).
const EMPTY_RESPONSE = 'Sorry! No relevant content was found in the knowledge base!'
// Prefiks odpowiedzi fake-chat, gdy retrieval dał fragmenty (K10 §4; złoto metadata_e6--47).
const SOURCES_PREFIX = 'Na podstawie źródeł: '

type Envelope<T> = { code: number; message?: string; data?: T }

type DocumentListed = {
  id: string
  name: string
  run: 'UNSTART' | 'RUNNING' | 'CANCEL' | 'DONE' | 'FAIL' | 'SCHEDULE'
  progress_msg: string
  meta_fields: Record<string, unknown>
  // `metadata` dokumentu w odpowiedzi listy to JSON-Schema (prezenter v0.27.2: turn2jsonschema).
  parser_config: { metadata?: { properties?: Record<string, unknown> } }
}

type ChatChunk = { document_id: string; document_name: string }

/** Rozwija kopertę RAGFlow: HTTP 200 + `code 0`, inaczej wyjątek (wzór: mcp-prod). */
async function ok<T>(response: APIResponse, label: string): Promise<T> {
  const body = (await response.json()) as Envelope<T>
  expect(response.status(), `${label}: HTTP ${response.status()} — ${body.message}`).toBe(200)
  expect(body.code, `${label}: ${body.message}`).toBe(0)
  return body.data as T
}

/** Login administratora; zwraca nagłówek Authorization (sesja, wzór: mcp-prod). */
async function apiLogin(request: APIRequestContext): Promise<string> {
  const response = await request.post('/api/v1/auth/login', {
    data: { email: ADMIN_EMAIL, password: ADMIN_PASSWORD },
  })
  await ok<unknown>(response, 'POST /api/v1/auth/login')
  const authorization = response.headers()['authorization']
  expect(authorization, 'login: brak nagłówka Authorization').toBeTruthy()
  return authorization!
}

/** Rekurencyjna lista plików katalogu (wzór: mcp-prod). */
function walk(dir: string, acc: string[]): void {
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const full = join(dir, entry.name)
    if (entry.isDirectory()) walk(full, acc)
    else if (entry.isFile()) acc.push(full)
  }
}

/**
 * PDF > 100 stron wg briefu: znany korpusowy rocznik GUS (745 stron); brak go w korpusie →
 * fixture `multi-batch-120.pdf` (120 stron) z repo (DEC-301, brief T8a).
 */
function bigPdf(): { path: string; name: string } {
  if (CORPUS !== '') {
    const paths: string[] = []
    walk(CORPUS, paths)
    const hit = paths.find((path) => basename(path) === GUS_NAME)
    if (hit !== undefined) return { path: hit, name: GUS_NAME }
  }
  return { path: MULTI_BATCH_PATH, name: MULTI_BATCH_NAME }
}

/** Upload multipart z dysku (wzór: mcp-prod); zwraca id dokumentu. */
async function uploadDoc(
  request: APIRequestContext,
  authorization: string,
  datasetId: string,
  path: string,
  mimeType: string,
): Promise<string> {
  const response = await request.post(`/api/v1/datasets/${datasetId}/documents`, {
    headers: { authorization },
    multipart: {
      file: { name: basename(path), mimeType, buffer: readFileSync(path) },
    },
  })
  const uploaded = await ok<{ id: string }[]>(
    response,
    `POST /datasets/{id}/documents (${basename(path)})`,
  )
  expect(uploaded.length, `upload ${basename(path)}: pusta lista dokumentów`).toBeGreaterThan(0)
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

/** Lista dokumentów (GET …/documents) z opcjonalnym filtrem query. */
async function listDocs(
  request: APIRequestContext,
  authorization: string,
  datasetId: string,
  params: Record<string, string> = {},
): Promise<{ docs: DocumentListed[]; total: number }> {
  const response = await request.get(`/api/v1/datasets/${datasetId}/documents`, {
    headers: { authorization },
    params,
  })
  return await ok<{ docs: DocumentListed[]; total: number }>(
    response,
    'GET /datasets/{id}/documents',
  )
}

/** Czeka na stan końcowy parsowania; zwraca wiersz dokumentu (wzór pollingu mcp-prod). */
async function awaitDone(
  request: APIRequestContext,
  authorization: string,
  datasetId: string,
  documentId: string,
  timeoutMs: number,
): Promise<DocumentListed> {
  const label = `poll dokumentu ${documentId}`
  const deadline = Date.now() + timeoutMs
  for (;;) {
    const page = await listDocs(request, authorization, datasetId, { id: documentId })
    const doc = page.docs.find((row) => row.id === documentId)
    expect(doc, `${label}: dokument na liście`).toBeDefined()
    if (doc!.run === 'DONE') return doc!
    if (doc!.run === 'FAIL' || doc!.run === 'CANCEL') {
      throw new Error(`${label}: run=${doc!.run}: ${doc!.progress_msg.slice(-400)}`)
    }
    if (Date.now() >= deadline) {
      throw new Error(`${label}: niedokończone po ${timeoutMs / 1000} s (run=${doc!.run})`)
    }
    await new Promise((resolve) => setTimeout(resolve, POLL_INTERVAL_MS))
  }
}

/** Tworzy czat na datasetcie z filtrem metadanych; zwraca id czatu. */
async function createChat(
  request: APIRequestContext,
  authorization: string,
  datasetId: string,
  filter: Record<string, unknown>,
): Promise<string> {
  const response = await request.post('/api/v1/chats', {
    headers: { authorization },
    data: {
      name: `real-metadata-chat-${Date.now()}`,
      dataset_ids: [datasetId],
      meta_data_filter: filter,
    },
  })
  const chat = await ok<{ id: string }>(response, 'POST /chats')
  return chat.id
}

/** Pytanie do czatu w trybie JSON (stream: false); zwraca data completions. */
async function complete(
  request: APIRequestContext,
  authorization: string,
  chatId: string,
  question: string,
): Promise<{ answer: string; reference: { chunks: ChatChunk[] } }> {
  const response = await request.post(`/api/v1/chats/${chatId}/completions`, {
    headers: { authorization },
    data: { question, stream: false },
  })
  return await ok<{ answer: string; reference: { chunks: ChatChunk[] } }>(
    response,
    'POST /chats/{id}/completions',
  )
}

// Stan z SC-01 dla testów kolejnych (konwencja e2e-real: serial — SC-01 przygotowuje dane,
// kolejne korzystają; wzór: mcp-prod).
test.describe.configure({ mode: 'serial' })

let datasetId = ''
let fixtureId = ''

test('SC-E6-1a-01 (real): auto-metadane przy parsowaniu — fixture dostaje rok/typ, korpus się parsuje', async ({
  request,
}) => {
  test.setTimeout(BIG_PARSE_TIMEOUT_MS)
  const authorization = await apiLogin(request)

  // Dataset z włączonymi auto-metadanymi i polami rok/typ (K11 §10f p. 3).
  const created = await request.post('/api/v1/datasets', {
    headers: { authorization },
    data: { name: DATASET_NAME, parser_config: { enable_metadata: true } },
  })
  datasetId = (await ok<{ id: string }>(created, 'POST /datasets')).id
  const config = await request.put(`/api/v1/datasets/${datasetId}/metadata/config`, {
    headers: { authorization },
    data: { metadata: FIELDS, built_in_metadata: [] },
  })
  await ok<unknown>(config, 'PUT /datasets/{id}/metadata/config')

  // 3 pliki z korpusu PL (w tym PDF > 100 stron — rocznik GUS; fallback fixture'a wg briefu)
  // + fixture metadanych z liniami rok/typ/autor.
  const big = bigPdf()
  const mdPath = `${CORPUS}/md/fixture_rag_strukturalny.md`
  const csvPath = `${CORPUS}/csv/nbp_kursy_srednie_2024.csv`
  const uploaded = [
    {
      id: await uploadDoc(request, authorization, datasetId, big.path, 'application/pdf'),
      name: big.name,
    },
    {
      id: await uploadDoc(request, authorization, datasetId, mdPath, 'text/markdown'),
      name: basename(mdPath),
    },
    {
      id: await uploadDoc(request, authorization, datasetId, csvPath, 'text/csv'),
      name: basename(csvPath),
    },
    {
      id: await uploadDoc(request, authorization, datasetId, FIXTURE_PATH, 'text/plain'),
      name: FIXTURE_NAME,
    },
  ]
  fixtureId = uploaded[3]!.id
  await parseDocs(
    request,
    authorization,
    datasetId,
    uploaded.map((doc) => doc.id),
  )

  // Wszystkie kończą „Sukces" (run=DONE); `meta_fields` dokładnie wg determinizmu fake-llm:
  // fixture {rok, typ} z linii; pliki korpusu — {} (bieg 2026-10-12: także GUS — w oknie
  // 16000 znaków tekstów chunków nie ma wartości enum; DEC-301, sekcja Obserwacja).
  // Asercje od fixture (rdzeń scenariusza), potem pliki korpusu.
  const expectedMeta: Record<string, Record<string, string>> = {
    [FIXTURE_NAME]: { rok: '2023', typ: 'raport' },
    [GUS_NAME]: {},
    [MULTI_BATCH_NAME]: {},
    [basename(mdPath)]: {},
    [basename(csvPath)]: {},
  }
  const inOrder = [uploaded[3]!, ...uploaded.slice(0, 3)]
  for (const doc of inOrder) {
    const row = await awaitDone(request, authorization, datasetId, doc.id, BIG_POLL_TIMEOUT_MS)
    expect(row.meta_fields, `meta_fields ${doc.name}`).toEqual(expectedMeta[doc.name])
    if (doc.id === fixtureId) {
      expect(row.progress_msg, 'log zadania fixture: wpis auto-metadanych').toContain(
        'Auto metadata: 2 fields',
      )
    }
  }
})

test('SC-E6-1a-02 (real): nie-JSON od modelu metadanych — parsowanie „Sukces”, meta bez zmian', async ({
  request,
}) => {
  const authorization = await apiLogin(request)
  expect(datasetId, 'SC-01 przygotował dataset').not.toBe('')

  // Treść z markerem FAKE_METADATA_INVALID → fake-llm odpowiada `not a json` (K10 2026-10-11b);
  // backend parsuje odpowiedź do {} i scalanie nic nie zmienia — bez porażki parsowania.
  const content =
    'FAKE_METADATA_INVALID\nrok: 2023\ntyp: raport\nTreść dokumentu testowego z odpowiedzią ' +
    'modelu metadanych, która nie jest poprawnym JSON-em.\n'
  const response = await request.post(`/api/v1/datasets/${datasetId}/documents`, {
    headers: { authorization },
    multipart: {
      file: { name: 'metadata-invalid.txt', mimeType: 'text/plain', buffer: Buffer.from(content) },
    },
  })
  const uploaded = await ok<{ id: string }[]>(response, 'POST /datasets/{id}/documents')
  const docId = uploaded[0]!.id
  await parseDocs(request, authorization, datasetId, [docId])
  const row = await awaitDone(request, authorization, datasetId, docId, 240_000)

  expect(row.meta_fields, 'meta_fields bez zmian (puste)').toEqual({})
  expect(row.progress_msg, 'log zadania: licznik bez dopasowań').toContain(
    'Auto metadata: 0 fields',
  )
  expect(row.progress_msg, 'log zadania bez stack trace').not.toContain('Traceback')
})

test('SC-E6-1a-03 (real): metadata_condition zawęża listę dokumentów; zły JSON → code 102', async ({
  request,
}) => {
  const authorization = await apiLogin(request)
  expect(datasetId, 'SC-01 przygotował dataset').not.toBe('')

  // rok = "2023" (STRING — wartość int daje 0 trafień, złoto metadata_e6--33).
  const stringHit = await listDocs(request, authorization, datasetId, {
    metadata_condition: JSON.stringify({
      logic: 'and',
      conditions: [{ name: 'rok', comparison_operator: '=', value: '2023' }],
    }),
  })
  expect(stringHit.total, 'filtr rok="2023": tylko fixture').toBe(1)
  expect(stringHit.docs[0]!.id, 'trafiony dokument to fixture').toBe(fixtureId)
  expect(stringHit.docs[0]!.name, 'nazwa trafionego dokumentu').toBe(FIXTURE_NAME)

  // Wartość int (złoto --33): "2023" vs 2023 → 0 trafień.
  const intHit = await listDocs(request, authorization, datasetId, {
    metadata_condition: JSON.stringify({
      logic: 'and',
      conditions: [{ name: 'rok', comparison_operator: '=', value: 2023 }],
    }),
  })
  expect(intHit.total, 'filtr rok=2023 (int): brak trafień').toBe(0)

  // Zły JSON → code 102 z komunikatem K11 §10f p. 1 (koperta bez `data`).
  const bad = await request.get(`/api/v1/datasets/${datasetId}/documents`, {
    headers: { authorization },
    params: { metadata_condition: 'not-json' },
  })
  const body = (await bad.json()) as Envelope<never>
  expect(bad.status(), 'zły metadata_condition: HTTP 200').toBe(200)
  expect(body.code, 'zły metadata_condition: code 102').toBe(102)
  expect(body.message, 'komunikat walidacji metadata_condition').toBe(
    'metadata_condition must be valid JSON: not-json.',
  )
})

test('SC-E6-1a-04 (real): czat z meta_data_filter manual — odpowiedź tylko z typ=raport; bez trafień → empty_response', async ({
  request,
}) => {
  const authorization = await apiLogin(request)
  expect(datasetId, 'SC-01 przygotował dataset').not.toBe('')

  const chatId = await createChat(request, authorization, datasetId, {
    method: 'manual',
    logic: 'and',
    manual: [{ key: 'typ', op: '=', value: 'raport' }],
  })

  // Pytanie to pierwsze zdanie fixture'a (wzór: mcp-prod) — fake-embed jest deterministyczny,
  // więc trafienie pochodzi z fixture'a; filtr typ=raport dopuszcza wyłącznie ten dokument.
  const question = 'Raporty z 2023 roku opisują stan środowiska w Polsce.'
  const hit = await complete(request, authorization, chatId, question)
  expect(hit.answer, 'odpowiedź z fragmentami źródeł').toContain(SOURCES_PREFIX)
  expect(hit.reference.chunks.length, 'retrieval dał fragmenty').toBeGreaterThan(0)
  for (const chunk of hit.reference.chunks) {
    expect(chunk.document_id, 'fragment wyłącznie z fixture (typ=raport)').toBe(fixtureId)
  }

  // Filtr bez trafień (typ=ustawa — nikt go nie ma) → empty_response i puste reference.
  const updated = await request.put(`/api/v1/chats/${chatId}`, {
    headers: { authorization },
    data: {
      meta_data_filter: {
        method: 'manual',
        logic: 'and',
        manual: [{ key: 'typ', op: '=', value: 'ustawa' }],
      },
    },
  })
  await ok<unknown>(updated, 'PUT /chats/{id}')
  const miss = await complete(request, authorization, chatId, question)
  expect(miss.answer, 'odpowiedź bez trafień = empty_response czatu').toBe(EMPTY_RESPONSE)
  expect(miss.reference.chunks, 'reference puste').toEqual([])
})

test('SC-E6-1a-05 (real): /retrieval z meta_data_filter auto — warunek z modelu zawęża do fixture', async ({
  request,
}) => {
  const authorization = await apiLogin(request)
  expect(datasetId, 'SC-01 przygotował dataset').not.toBe('')

  // fake-llm (K10 2026-10-11b) czyta `- Dostępne klucze metadanych:` i pytanie: „raporty z 2023"
  // generuje warunek rok = 2023 ("raporty" nie trafia w granice słowa wartości enum), więc
  // dozwolony jest wyłącznie fixture z meta rok="2023".
  const response = await request.post('/api/v1/retrieval', {
    headers: { authorization },
    data: {
      question: 'raporty z 2023',
      dataset_ids: [datasetId],
      meta_data_filter: { method: 'auto' },
    },
  })
  const result = await ok<{ chunks: ChatChunk[]; total: number }>(response, 'POST /retrieval')
  expect(result.chunks.length, 'retrieval dał fragmenty').toBeGreaterThan(0)
  for (const chunk of result.chunks) {
    expect(chunk.document_id, 'fragment wyłącznie z fixture (warunek rok=2023)').toBe(fixtureId)
  }
})

test('SC-E6-1a-06 (real): pomiar 10 000 dokumentów — realizuje go T6, nie ten spec', async () => {
  test.skip(
    true,
    'pomiar 10k filtru metadanych biega w T6 (tools/perf/meta-filter-10k.sh); brief T8a: NIE duplikować',
  )
})

test('SC-E6-1a-07 (real): zmiana listy pól datasetu — dotychczasowe meta_fields dokumentu nie znikają', async ({
  request,
}) => {
  const authorization = await apiLogin(request)
  expect(datasetId, 'SC-01 przygotował dataset').not.toBe('')

  // Zmiana listy pól datasetu: dopisane `autor` (K11 §10f p. 3 — PUT nie rusza enable_metadata).
  const config = await request.put(`/api/v1/datasets/${datasetId}/metadata/config`, {
    headers: { authorization },
    data: {
      metadata: [...FIELDS, { key: 'autor', type: 'string' }],
      built_in_metadata: [],
    },
  })
  const saved = await ok<{ metadata: { key: string }[] }>(
    config,
    'PUT /datasets/{id}/metadata/config',
  )
  expect(
    saved.metadata.map((field) => field.key),
    'dataset po zapisie ma pola rok/typ/autor',
  ).toEqual(['rok', 'typ', 'autor'])

  // K11 §10f p. 4 (ZAMROŻONY): dokument dziedziczy parser_config datasetu PRZY UPLOADZIE —
  // PUT datasetu nie propaguje do już wgranych dokumentów (jak upstream: v0.27.2 update_dataset
  // pisze tylko wiersz KB, a UI zapisuje ustawienia datasetu trasą metadata/config bez stron
  // dokumentowych). Stąd parser_config dokumentu zostaje przy rok/typ, a meta_fields nie znikają.
  const before = await listDocs(request, authorization, datasetId, { id: fixtureId })
  expect(
    Object.keys(before.docs[0]!.parser_config.metadata!.properties ?? {}),
    'parser_config dokumentu bez propagacji zmiany datasetu (K11 §10f p. 4)',
  ).toEqual(['rok', 'typ'])
  expect(before.docs[0]!.meta_fields, 'meta_fields fixture bez zmian').toEqual({
    rok: '2023',
    typ: 'raport',
  })
})

test('SC-E6-1a-07b (real): nowe pola działają po „Parsuj ponownie” — konfiguracja dokumentu (S-320)', async ({
  request,
}) => {
  const authorization = await apiLogin(request)
  expect(datasetId, 'SC-01 przygotował dataset').not.toBe('')

  // Nowe pola dla JUŻ wgranego dokumentu nadaje konfiguracja dokumentu (S-320, K11 §10f p. 2,
  // ciało {metadata: <JSON-Schema>}) — ścieżka upstream (UI: ustawienia pojedynczego pliku);
  // wariant P1 decyzji TL 2026-10-12. Schemat obejmuje rok/typ/autor: scalanie nie może zgubić
  // starych pól (SC-07 część 1), a fixture zawiera linię `autor: Jan Testowy`.
  const docConfig = await request.put(
    `/api/v1/datasets/${datasetId}/documents/${fixtureId}/metadata/config`,
    {
      headers: { authorization },
      data: {
        metadata: {
          type: 'object',
          properties: {
            rok: { type: 'string', description: 'Rok, którego dotyczą dane' },
            typ: { type: 'string', enum: ['raport', 'rocznik', 'ustawa'] },
            autor: { type: 'string' },
          },
          additionalProperties: false,
        },
      },
    },
  )
  await ok<unknown>(docConfig, 'PUT /datasets/{id}/documents/{id}/metadata/config')

  // „Parsuj ponownie” (POST parse na DONE → clear_existing, jak upstream): stare meta_fields
  // nie znikają, nowe pole `autor` się dopisuje (log: jedyna zmiana to autor → `1 fields`).
  await parseDocs(request, authorization, datasetId, [fixtureId])
  const after = await awaitDone(request, authorization, datasetId, fixtureId, 240_000)
  expect(after.meta_fields, 'meta_fields fixture po ponowieniu').toEqual({
    rok: '2023',
    typ: 'raport',
    autor: 'Jan Testowy',
  })
  expect(after.progress_msg, 'log zadania: dopisane tylko nowe pole').toContain(
    'Auto metadata: 1 fields',
  )
})
