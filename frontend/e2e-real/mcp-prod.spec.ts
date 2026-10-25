// Scenariusze SC-E6-2-01…04 i -07 (K17 §5, brief T8 WP E6-2): klient MCP przez proxy `web`
// na produkcyjnym stosie clean-install z profilem `mcp` (WD_CI_PROFILES=mcp w clean-install.sh)
// — jedyny test całego łańcucha klient → web → mcp → api (kontrakt mcp_wd stawia serwer MCP
// obok API bez `web`, a testy T5 bez `web`). Klient = surowe HTTP z Node (JSON-RPC 2.0):
// transport streamable HTTP to `POST /mcp` z `Accept: application/json, text/event-stream`
// (serwer WD działa z `json_response=True`, więc odpowiedź to `application/json`), transport
// SSE to `GET /sse` — pierwszy event `endpoint` wskazuje `/messages/?session_id=…`, żądania
// idą POST-em na ten adres, a odpowiedzi czytane są ze strumienia SSE.
// Dane przygotowuje API przez `web` (bez SQL, bez seedu K9 — konwencja e2e-real): admin z
// WD_CI_ADMIN_* zakłada konta A i B (POST /api/wd/v1/users — rejestracja POST /users jest
// w czystej instalacji wyłączona), konta dostają klucze API (POST /system/tokens), użytkownik
// A — dataset z najmniejszym PDF-em korpusu WD_REAL_CORPUS (fallback: fixture multi-batch-120.pdf
// z repo) sparsowanym do DONE, użytkownik B — własny pusty dataset. Pytanie retrievalu to
// pierwsze zdanie chunku z polskim znakiem: fake-embed jest deterministyczny, więc zdanie
// wzięte z treści dokumentu daje trafienie (wzór real-corpus.spec.ts). Klucze API nie trafiają
// na stdout — asercje dotyczą wyłącznie treści fragmentów i list zasobów.
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { basename, join } from 'node:path'
import { fileURLToPath } from 'node:url'

import { expect, test } from '@playwright/test'
import type { APIRequestContext, APIResponse } from '@playwright/test'

import { containerStats, serviceContainerId } from './helpers/worker'

const BASE = (process.env.WD_CI_BASE_URL ?? '').replace(/\/+$/, '')
const ADMIN_EMAIL = process.env.WD_CI_ADMIN_EMAIL ?? ''
const ADMIN_PASSWORD = process.env.WD_CI_ADMIN_PASSWORD ?? ''
const PROJECT = process.env.WD_CI_PROJECT ?? ''
const CORPUS = process.env.WD_REAL_CORPUS ?? ''

const USER_A_EMAIL = 'mcp-prod-a@wd-ci.test'
const USER_B_EMAIL = 'mcp-prod-b@wd-ci.test'
// Stała testowa kont zakładanych przez admina (nie sekret); hasło nigdy nie idzie na stdout.
const USER_PASSWORD = 'wd-mcp-prod-1'
const DATASET_A_NAME = 'mcp-prod-ds-a'
const DATASET_B_NAME = 'mcp-prod-ds-b'
const BAD_KEY = 'ragflow-mcp-prod-invalid-key'

// K17 §4: dokładnie trzy narzędzia upstream; K17 §1/§3: treści 401 i 503 z kontraktu.
const EXPECTED_TOOLS = ['ragflow_list_chats', 'ragflow_list_datasets', 'ragflow_retrieval']
const NO_AUTH_BODY = { error: 'Missing or invalid authorization header' }
// Polskie diakrytyki — asercja „fragment z poprawnymi polskimi znakami” (brief SC-01).
const PL_MARK = /[ąćęłńóśźż]/
// SC-E6-2-07: 20 równoległych retrievalli, RSS usługi mcp < limit 256 MB (K17 §1).
const PARALLEL_CALLS = 20
const RSS_LIMIT_BYTES = 256 * 1024 * 1024
// Limit czekania na pierwszy event `endpoint` strumienia SSE (brief SC-02) i na parsowanie PDF.
const SSE_ENDPOINT_TIMEOUT_MS = 5_000
const PARSE_TIMEOUT_MS = 900_000
const PARSE_INTERVAL_MS = 3_000

type Envelope<T> = { code: number; message: string; data: T }

type ChunkHit = {
  dataset_id: string | null
  content: string | null
}

type JsonRpcError = { code: number; message: string }

type RpcOutcome = { result?: unknown; error?: JsonRpcError }

/** Rozwija kopertę RAGFlow: HTTP 200 + `code 0`, inaczej wyjątek (wzór: real-concurrency). */
async function ok<T>(response: APIResponse, label: string): Promise<T> {
  const body = (await response.json()) as Envelope<T>
  expect(response.status(), `${label}: HTTP ${response.status()} — ${body.message}`).toBe(200)
  expect(body.code, `${label}: ${body.message}`).toBe(0)
  return body.data
}

/** Login przez `web`: zwraca nagłówek Authorization (token sesyjny, wzór: support.py). */
async function apiLogin(
  request: APIRequestContext,
  email: string,
  password: string,
): Promise<string> {
  const response = await request.post('/api/v1/auth/login', { data: { email, password } })
  await ok<unknown>(response, `POST /api/v1/auth/login (${email})`)
  const authorization = response.headers()['authorization']
  expect(authorization, `login ${email}: brak nagłówka Authorization`).toBeTruthy()
  return authorization!
}

/** Konto zakładane przez admina (POST /api/wd/v1/users; rejestracja /users jest wyłączona). */
async function adminCreateUser(
  request: APIRequestContext,
  adminAuthorization: string,
  email: string,
): Promise<void> {
  const response = await request.post('/api/wd/v1/users', {
    headers: { authorization: adminAuthorization },
    data: { email, nickname: email.split('@')[0], password: USER_PASSWORD },
  })
  expect(response.status(), `POST /api/wd/v1/users (${email}): ${await response.text()}`).toBe(201)
}

/** Nowy klucz API konta (POST /system/tokens z sesją; kształt jak register_user w support.py). */
async function createApiKey(request: APIRequestContext, authorization: string): Promise<string> {
  const response = await request.post('/api/v1/system/tokens', { headers: { authorization } })
  const data = await ok<{ token: string }>(response, 'POST /api/v1/system/tokens')
  return data.token
}

/** Rekurencyjna lista plików katalogu (wzór: real-concurrency.spec.ts). */
function walk(dir: string, acc: string[]): void {
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const full = join(dir, entry.name)
    if (entry.isDirectory()) walk(full, acc)
    else if (entry.isFile()) acc.push(full)
  }
}

/**
 * Dokument datasetu A: najmniejszy PDF korpusu WD_REAL_CORPUS (brief: preferuj mały polski
 * PDF). Brak korpusu albo PDF-u, a także kandydat, którego treść nie daje polskich znaków
 * (skany idą przez fake-vision, a opisy obrazów są ASCII) → następny kandydat: fixture
 * multi-batch-120.pdf z repo (polskie słowa z pełnym zestawem diakrytyków, generator
 * make-multi-batch-pdf.py). Tylko NAJMNIEJSZY PDF korpusu wchodzi do gry — większe
 * (rocznik GUS 745 stron, projekt ustawy 1421 strony) parsowałyby się minuty dłużej.
 */
function pdfCandidates(): string[] {
  const candidates: string[] = []
  if (CORPUS !== '') {
    const paths: string[] = []
    walk(CORPUS, paths)
    const pdfs = paths.filter((path) => path.toLowerCase().endsWith('.pdf'))
    pdfs.sort((a, b) => statSync(a).size - statSync(b).size)
    if (pdfs.length > 0) candidates.push(pdfs[0]!)
  }
  candidates.push(fileURLToPath(new URL('../e2e/fixtures/multi-batch-120.pdf', import.meta.url)))
  return candidates
}

/** Pierwsze zdanie pierwszego niepustego wiersza (bez nagłówków) — wzór: real-corpus.spec.ts. */
function firstSentence(text: string): string {
  for (const raw of text.split('\n')) {
    const line = raw.trim()
    if (line === '' || line.startsWith('#')) continue
    return line.split(/(?<=[.!?])\s+/)[0]?.trim() ?? ''
  }
  return ''
}

type Prepared = {
  keyA: string
  keyB: string
  datasetAId: string
  datasetBId: string
  question: string
  marker: string
}

let prepared: Prepared | null = null

/** Upload PDF (multipart), start parsowania i czekanie na DONE; zwraca id dokumentu. */
async function ingestAndParse(
  request: APIRequestContext,
  headers: { authorization: string },
  datasetId: string,
  pdfPath: string,
): Promise<string> {
  const uploaded = await request.post(`/api/v1/datasets/${datasetId}/documents`, {
    headers,
    multipart: {
      file: { name: basename(pdfPath), mimeType: 'application/pdf', buffer: readFileSync(pdfPath) },
    },
  })
  const documents = await ok<{ id: string }[]>(uploaded, 'POST /datasets/{id}/documents')
  expect(documents.length, 'upload PDF zwraca dokument').toBeGreaterThan(0)
  const documentId = documents[0]!.id
  const parsed = await request.post(`/api/v1/datasets/${datasetId}/documents/parse`, {
    headers,
    data: { document_ids: [documentId] },
  })
  await ok<unknown>(parsed, 'POST /datasets/{id}/documents/parse')
  const deadline = Date.now() + PARSE_TIMEOUT_MS
  for (;;) {
    const listing = await request.get(`/api/v1/datasets/${datasetId}/documents`, {
      headers,
      params: { page: 1, page_size: 30 },
    })
    const docs = await ok<{ docs: { id: string; run: string | null }[] }>(
      listing,
      'GET /datasets/{id}/documents',
    )
    const run = docs.docs.find((doc) => doc.id === documentId)?.run ?? null
    if (run === 'DONE') return documentId
    if (run === 'FAIL' || run === 'CANCEL') {
      throw new Error(`parsowanie ${basename(pdfPath)}: run=${run}`)
    }
    if (Date.now() >= deadline) {
      throw new Error(`parsowanie niedokończone po ${PARSE_TIMEOUT_MS / 1000} s (run=${run})`)
    }
    await new Promise((resolve) => setTimeout(resolve, PARSE_INTERVAL_MS))
  }
}

/**
 * Dane wszystkich scenariuszy, raz na bieg (testy serialne, konwencja e2e-real): konta A i B
 * z kluczami API, dataset A z jednym PDF-em sparsowanym do DONE, pusty dataset B. Pytanie
 * retrievalu i marker treści pochodzą z pierwszego chunku z polskim znakiem.
 */
async function prepare(request: APIRequestContext): Promise<Prepared> {
  if (prepared !== null) return prepared

  const adminAuthorization = await apiLogin(request, ADMIN_EMAIL, ADMIN_PASSWORD)
  await adminCreateUser(request, adminAuthorization, USER_A_EMAIL)
  await adminCreateUser(request, adminAuthorization, USER_B_EMAIL)
  const keyA = await createApiKey(request, await apiLogin(request, USER_A_EMAIL, USER_PASSWORD))
  const keyB = await createApiKey(request, await apiLogin(request, USER_B_EMAIL, USER_PASSWORD))

  // Dataset A: kandydaci PDF → upload (multipart) → parse → DONE (wzór: support.ingest_dataset).
  const headersA = { authorization: `Bearer ${keyA}` }
  const created = await request.post('/api/v1/datasets', {
    headers: headersA,
    data: { name: DATASET_A_NAME },
  })
  const datasetA = await ok<{ id: string }>(created, 'POST /api/v1/datasets (A)')

  // Pytanie i marker z treści dokumentu: pierwszy chunk z polskim znakiem (brief SC-01).
  let question = ''
  for (const pdfPath of pdfCandidates()) {
    const documentId = await ingestAndParse(request, headersA, datasetA.id, pdfPath)
    const chunksResponse = await request.get(
      `/api/v1/datasets/${datasetA.id}/documents/${documentId}/chunks`,
      { headers: headersA, params: { page: 1, page_size: 50 } },
    )
    const chunks = await ok<{ chunks: { content: string }[] }>(
      chunksResponse,
      'GET /datasets/{id}/documents/{id}/chunks',
    )
    expect(chunks.chunks.length, `chunki ${basename(pdfPath)}`).toBeGreaterThan(0)
    const plChunk = chunks.chunks.find((chunk) => PL_MARK.test(chunk.content))
    if (plChunk !== undefined) {
      // fake-embed: pytanie dosłownie z treści daje najwyższe podobieństwo do swojego chunku
      // (wzór real-corpus); za krótkie zdanie zastępujemy wycinkiem treści.
      const sentence = firstSentence(plChunk.content)
      question = sentence.length >= 12 ? sentence : plChunk.content.slice(0, 150)
      break
    }
    // Kandydat bez polskich znaków (np. skan opisany przez fake-vision) — usuń i próbuj dalej.
    const removed = await request.delete(`/api/v1/datasets/${datasetA.id}/documents`, {
      headers: headersA,
      data: { ids: [documentId] },
    })
    await ok<unknown>(removed, `DELETE documents (${basename(pdfPath)})`)
  }
  if (question === '') {
    throw new Error('korpus i fixture: żaden kandydat PDF nie daje chunku z polskimi znakami')
  }
  expect(question.length, 'pytanie retrievalu z treści dokumentu').toBeGreaterThan(0)

  // Dataset B: pusty, wyłącznie dla SC-E6-2-03.
  const createdB = await request.post('/api/v1/datasets', {
    headers: { authorization: `Bearer ${keyB}` },
    data: { name: DATASET_B_NAME },
  })
  const datasetB = await ok<{ id: string }>(createdB, 'POST /api/v1/datasets (B)')

  prepared = {
    keyA,
    keyB,
    datasetAId: datasetA.id,
    datasetBId: datasetB.id,
    question,
    marker: question.slice(0, 30),
  }
  return prepared
}

// --- transport streamable HTTP: `POST /mcp`, JSON-RPC 2.0, odpowiedź application/json ---

let rpcId = 0

/** Jedno żądanie JSON-RPC na `POST /mcp` (serwer bezstanowy — każde POST niezależne). */
async function httpRpc(
  method: string,
  params: Record<string, unknown>,
  auth: string | null,
): Promise<RpcOutcome & { status: number }> {
  const response = await fetch(`${BASE}/mcp`, {
    method: 'POST',
    headers: {
      'content-type': 'application/json',
      accept: 'application/json, text/event-stream',
      ...(auth === null ? {} : { authorization: auth }),
    },
    body: JSON.stringify({ jsonrpc: '2.0', id: ++rpcId, method, params }),
  })
  return { ...((await response.json()) as RpcOutcome), status: response.status }
}

/** Powiadomienie `notifications/initialized` (bez id — bez odpowiedzi). */
async function httpInitialized(auth: string): Promise<void> {
  const response = await fetch(`${BASE}/mcp`, {
    method: 'POST',
    headers: {
      'content-type': 'application/json',
      accept: 'application/json, text/event-stream',
      authorization: auth,
    },
    body: JSON.stringify({ jsonrpc: '2.0', method: 'notifications/initialized' }),
  })
  expect(response.status, 'POST notifications/initialized: status').toBe(202)
}

/** Wynik `tools/call` jako tekst bloków TextContent (wzór: session_helpers.text_of). */
function callText(outcome: RpcOutcome): string {
  const result = outcome.result as { content?: { type: string; text: string }[] } | undefined
  return (result?.content ?? [])
    .filter((block) => block.type === 'text')
    .map((block) => block.text)
    .join('')
}

/** Fragmenty z odpowiedzi `ragflow_retrieval` (TextContent = JSON z polami API). */
function retrievalChunks(outcome: RpcOutcome): ChunkHit[] {
  return (JSON.parse(callText(outcome)) as { chunks: ChunkHit[] }).chunks
}

// --- transport SSE: `GET /sse` → event `endpoint` → `POST /messages/?session_id=…` ---

/**
 * Sesja MCP na strumieniu SSE. `connect` czeka ≤ 5 s na pierwszy event `endpoint`; żądania
 * idą POST-em na adres z eventu (ścieżka względna — działa przez proxy `web`, K17 §2), a
 * odpowiedzi (`event: message` z ciałem JSON-RPC) są dispatchowane po `id` do czekających.
 */
class SseMcp {
  private pending = new Map<number, (outcome: RpcOutcome) => void>()
  private endpointWaiters: { resolve: (path: string) => void; reject: (err: Error) => void }[] = []
  private nextId = 1
  private reader: ReadableStreamDefaultReader<Uint8Array> | null = null
  private buffer = ''
  private decoder = new TextDecoder()
  private pump: Promise<void> = Promise.resolve()
  private closed = false

  private constructor(private readonly auth: string) {}

  endpointPath = ''

  static async connect(auth: string): Promise<SseMcp> {
    const response = await fetch(`${BASE}/sse`, {
      headers: { accept: 'text/event-stream', authorization: auth },
    })
    expect(response.status, 'GET /sse: status').toBe(200)
    expect(
      response.headers.get('content-type') ?? '',
      'GET /sse: strumień text/event-stream',
    ).toContain('text/event-stream')
    expect(response.body, 'GET /sse: ciało strumienia').not.toBeNull()

    const session = new SseMcp(auth)
    session.reader = response.body!.getReader()
    const endpointPromise = new Promise<string>((resolve, reject) => {
      const timer = setTimeout(
        () => reject(new Error(`SSE: brak eventu endpoint w ${SSE_ENDPOINT_TIMEOUT_MS} ms`)),
        SSE_ENDPOINT_TIMEOUT_MS,
      )
      session.endpointWaiters.push({
        resolve: (path: string) => {
          clearTimeout(timer)
          resolve(path)
        },
        reject: (err: Error) => {
          clearTimeout(timer)
          reject(err)
        },
      })
    })
    session.pump = session.readLoop()
    session.endpointPath = await endpointPromise
    return session
  }

  private async readLoop(): Promise<void> {
    try {
      for (;;) {
        const { done, value } = await this.reader!.read()
        if (done) break
        this.buffer += this.decoder.decode(value, { stream: true })
        for (;;) {
          const match = /\r?\n\r?\n/.exec(this.buffer)
          if (match === null) break
          const raw = this.buffer.slice(0, match.index)
          this.buffer = this.buffer.slice(match.index + match[0].length)
          this.onEvent(raw)
        }
      }
    } catch {
      // strumień zerwany (np. abort klienta) — porządki w finally
    } finally {
      this.closed = true
      const waiters = this.endpointWaiters
      this.endpointWaiters = []
      for (const waiter of waiters) {
        waiter.reject(new Error('SSE: strumień zamknięty przed eventem endpoint'))
      }
      const pending = [...this.pending.entries()]
      this.pending.clear()
      for (const [id, resolve] of pending) {
        resolve({ error: { code: -1, message: `SSE: strumień zamknięty (id=${id})` } })
      }
    }
  }

  /** Parsuje jeden blok SSE: `event: …` + `data: …` (domyślny event = message). */
  private onEvent(raw: string): void {
    let name = 'message'
    const dataLines: string[] = []
    for (const line of raw.split(/\r?\n/)) {
      if (line.startsWith('event:')) name = line.slice('event:'.length).trim()
      else if (line.startsWith('data:')) dataLines.push(line.slice('data:'.length).trimStart())
    }
    if (dataLines.length === 0) return
    const data = dataLines.join('\n')
    if (name === 'endpoint') {
      this.endpointPath = data
      for (const waiter of this.endpointWaiters.splice(0)) waiter.resolve(data)
      return
    }
    if (name !== 'message') return
    let parsed: { id?: number; result?: unknown; error?: JsonRpcError }
    try {
      parsed = JSON.parse(data) as typeof parsed
    } catch {
      return
    }
    if (typeof parsed.id === 'number' && this.pending.has(parsed.id)) {
      const resolve = this.pending.get(parsed.id)!
      this.pending.delete(parsed.id)
      resolve({ result: parsed.result, error: parsed.error })
    }
  }

  /** Żądanie JSON-RPC: POST na adres z eventu `endpoint`, odpowiedź ze strumienia. */
  async request(method: string, params: Record<string, unknown>): Promise<RpcOutcome> {
    const id = this.nextId++
    const outcome = new Promise<RpcOutcome>((resolve) => this.pending.set(id, resolve))
    const response = await fetch(`${BASE}${this.endpointPath}`, {
      method: 'POST',
      headers: { 'content-type': 'application/json', authorization: this.auth },
      body: JSON.stringify({ jsonrpc: '2.0', id, method, params }),
    })
    expect(response.status, `POST ${this.endpointPath} (${method}): status`).toBe(202)
    await response.body?.cancel()
    return outcome
  }

  async initialized(): Promise<void> {
    const response = await fetch(`${BASE}${this.endpointPath}`, {
      method: 'POST',
      headers: { 'content-type': 'application/json', authorization: this.auth },
      body: JSON.stringify({ jsonrpc: '2.0', method: 'notifications/initialized' }),
    })
    expect(response.status, 'POST notifications/initialized: status').toBe(202)
    await response.body?.cancel()
  }

  /** Zamyka strumień; readLoop rozstrzyga pozostałe żądania (test nie może wisieć). */
  async close(): Promise<void> {
    if (!this.closed) await this.reader?.cancel().catch(() => {})
    await this.pump.catch(() => {})
  }
}

/** Asercje `initialize` wspólne dla obu transportów (K17 §2); zwraca serverInfo. */
function expectInitialized(outcome: RpcOutcome): { name: string; experimental: unknown } {
  expect(outcome.error, 'initialize: brak błędu JSON-RPC').toBeUndefined()
  const result = outcome.result as {
    serverInfo: { name: string }
    capabilities: { experimental: unknown }
  }
  return { name: result.serverInfo.name, experimental: result.capabilities.experimental }
}

// Testy serialne: SC-01 przygotowuje dane, kolejne korzystają (konwencja e2e-real).
test.describe.configure({ mode: 'serial' })

test('SC-E6-2-01: initialize, tools/list, list_datasets i retrieval przez web → /mcp', async ({
  request,
}) => {
  test.setTimeout(PARSE_TIMEOUT_MS + 600_000)
  expect(BASE, 'WD_CI_BASE_URL od clean-install.sh').not.toBe('')

  const data = await prepare(request)
  const authA = `Bearer ${data.keyA}`

  const initialized = await httpRpc(
    'initialize',
    {
      protocolVersion: '2025-11-25',
      capabilities: {},
      clientInfo: { name: 'wd-e2e-real-mcp', version: '0.0.0' },
    },
    authA,
  )
  await httpInitialized(authA)
  const initializedInfo = expectInitialized(initialized)
  expect(initializedInfo.name, 'serverInfo.name (K17 §2)').toBe('ragflow-mcp-server')
  expect(initializedInfo.experimental, 'experimental = {} (K17 §2)').toEqual({})

  const tools = await httpRpc('tools/list', {}, authA)
  expect(tools.error, 'tools/list: brak błędu JSON-RPC').toBeUndefined()
  const toolNames = (tools.result as { tools: { name: string }[] }).tools.map((tool) => tool.name)
  expect([...toolNames].sort(), 'tools/list → dokładnie trzy narzędzia upstream').toEqual(
    EXPECTED_TOOLS,
  )

  const datasets = await httpRpc(
    'tools/call',
    { name: 'ragflow_list_datasets', arguments: {} },
    authA,
  )
  expect(datasets.error, 'list_datasets: brak błędu JSON-RPC').toBeUndefined()
  const datasetsText = callText(datasets)
  expect(datasetsText, 'lista datasetów A zawiera dataset A').toContain(DATASET_A_NAME)
  expect(datasetsText, 'lista datasetów A zawiera id datasetu A').toContain(data.datasetAId)

  const retrieved = await httpRpc(
    'tools/call',
    { name: 'ragflow_retrieval', arguments: { question: data.question } },
    authA,
  )
  expect(retrieved.error, 'retrieval: brak błędu JSON-RPC').toBeUndefined()
  const hits = retrievalChunks(retrieved)
  expect(hits.length, 'retrieval zwraca fragmenty').toBeGreaterThan(0)
  const fromA = hits.find((chunk) => chunk.dataset_id === data.datasetAId)
  if (fromA === undefined) {
    throw new Error(
      `retrieval: brak fragmentu z datasetu A (chunks=${callText(retrieved).slice(0, 400)})`,
    )
  }
  expect(fromA.content ?? '', 'fragment z datasetu A ma polskie znaki').toMatch(PL_MARK)
  expect(fromA.content ?? '', 'fragment z datasetu A zawiera treść pytania').toContain(data.marker)
})

test('SC-E6-2-02: ten sam przepływ przez web → /sse (endpoint ≤ 5 s, odpowiedzi ze strumienia)', async ({
  request,
}) => {
  test.setTimeout(300_000)
  const data = await prepare(request)
  const authA = `Bearer ${data.keyA}`

  const session = await SseMcp.connect(authA)
  try {
    expect(session.endpointPath, 'event endpoint → /messages/?session_id=…').toMatch(
      /^\/messages\/\?session_id=/,
    )
    const initialized = await session.request('initialize', {
      protocolVersion: '2025-11-25',
      capabilities: {},
      clientInfo: { name: 'wd-e2e-real-mcp', version: '0.0.0' },
    })
    await session.initialized()
    const initializedInfo = expectInitialized(initialized)
    expect(initializedInfo.name, 'SSE serverInfo.name (K17 §2)').toBe('ragflow-mcp-server')
    expect(initializedInfo.experimental, 'SSE: experimental = {} (K17 §2)').toEqual({})

    const tools = await session.request('tools/list', {})
    expect(tools.error, 'SSE tools/list: brak błędu JSON-RPC').toBeUndefined()
    const toolNames = (tools.result as { tools: { name: string }[] }).tools.map((tool) => tool.name)
    expect([...toolNames].sort(), 'SSE tools/list → trzy narzędzia').toEqual(EXPECTED_TOOLS)

    const datasets = await session.request('tools/call', {
      name: 'ragflow_list_datasets',
      arguments: {},
    })
    expect(datasets.error, 'SSE list_datasets: brak błędu').toBeUndefined()
    expect(callText(datasets), 'SSE lista = datasety A').toContain(DATASET_A_NAME)
    expect(callText(datasets), 'SSE lista zawiera id datasetu A').toContain(data.datasetAId)

    const retrieved = await session.request('tools/call', {
      name: 'ragflow_retrieval',
      arguments: { question: data.question },
    })
    expect(retrieved.error, 'SSE retrieval: brak błędu').toBeUndefined()
    const hits = retrievalChunks(retrieved)
    const fromA = hits.find((chunk) => chunk.dataset_id === data.datasetAId)
    if (fromA === undefined) {
      throw new Error(
        `SSE retrieval: brak fragmentu z datasetu A (chunks=${callText(retrieved).slice(0, 400)})`,
      )
    }
    expect(fromA.content ?? '', 'SSE fragment z datasetu A ma polskie znaki').toMatch(PL_MARK)
    expect(fromA.content ?? '', 'SSE fragment zawiera treść pytania').toContain(data.marker)
  } finally {
    await session.close()
  }
})

test('SC-E6-2-03: klucz B nie widzi datasetu A (lista, opis narzędzia, retrieval)', async ({
  request,
}) => {
  test.setTimeout(300_000)
  const data = await prepare(request)

  const datasets = await httpRpc(
    'tools/call',
    { name: 'ragflow_list_datasets', arguments: {} },
    `Bearer ${data.keyB}`,
  )
  expect(datasets.error, 'list_datasets B: brak błędu').toBeUndefined()
  const datasetsText = callText(datasets)
  expect(datasetsText, 'lista B zawiera dataset B').toContain(DATASET_B_NAME)
  expect(datasetsText, 'lista B zawiera id datasetu B').toContain(data.datasetBId)
  expect(datasetsText, 'lista B bez nazwy datasetu A').not.toContain(DATASET_A_NAME)
  expect(datasetsText, 'lista B bez id datasetu A').not.toContain(data.datasetAId)

  const tools = await httpRpc('tools/list', {}, `Bearer ${data.keyB}`)
  expect(tools.error, 'tools/list B: brak błędu').toBeUndefined()
  const toolsList = tools.result as { tools: { name: string; description: string }[] }
  const description = toolsList.tools.find((tool) => tool.name === 'ragflow_retrieval')?.description
  expect(description, 'opis ragflow_retrieval obecny').toBeTruthy()
  expect(description!, 'opis zawiera dataset B').toContain(DATASET_B_NAME)
  expect(description!, 'opis bez nazwy datasetu A').not.toContain(DATASET_A_NAME)
  expect(description!, 'opis bez id datasetu A').not.toContain(data.datasetAId)

  // Retrieval bez dataset_ids: serwer sam rozwiązuje datasety konta — u B tylko pusty dataset B.
  const retrieved = await httpRpc(
    'tools/call',
    { name: 'ragflow_retrieval', arguments: { question: data.question } },
    `Bearer ${data.keyB}`,
  )
  expect(retrieved.error, 'retrieval B: brak błędu').toBeUndefined()
  const hits = retrievalChunks(retrieved)
  expect(
    hits.every((chunk) => chunk.dataset_id !== data.datasetAId),
    'retrieval B bez chunków A',
  ).toBe(true)
  expect(
    hits.every((chunk) => !(chunk.content ?? '').includes(data.marker)),
    'retrieval B bez treści dokumentu A',
  ).toBe(true)
})

test('SC-E6-2-04: brak klucza → 401 (oba transporty); zły klucz → błąd JSON-RPC Unauthorized', async ({
  request,
}) => {
  test.setTimeout(300_000)
  await prepare(request)

  // (a) brak klucza: middleware serwera odpowiada 401 z treścią K17 §3 (oba transporty).
  const noAuthMcp = await httpRpc('tools/list', {}, null)
  expect(noAuthMcp.status, 'POST /mcp bez klucza → 401').toBe(401)
  expect(noAuthMcp, 'treść 401 z K17 §3').toEqual({ ...NO_AUTH_BODY, status: 401 })
  const noAuthSse = await fetch(`${BASE}/sse`, { headers: { accept: 'text/event-stream' } })
  expect(noAuthSse.status, 'GET /sse bez klucza → 401').toBe(401)
  expect(await noAuthSse.json(), 'treść 401 SSE z K17 §3').toEqual(NO_AUTH_BODY)

  // (b) zły klucz: middleware przepuszcza (sprawdza tylko obecność — initialize przechodzi,
  // K17 §3.4), a błąd wychodzi przy pierwszym wywołaniu API WD z narzędzia; `initialize` jest
  // wymagane przez protokół przed `tools/list` (wzór: recorder mcp_runner._execute_mcp).
  const badInit = await httpRpc(
    'initialize',
    {
      protocolVersion: '2025-11-25',
      capabilities: {},
      clientInfo: { name: 'wd-e2e-real-mcp', version: '0.0.0' },
    },
    `Bearer ${BAD_KEY}`,
  )
  expect(badInit.error, 'initialize ze złym kluczem przechodzi (K17 §3.4)').toBeUndefined()
  await httpInitialized(`Bearer ${BAD_KEY}`)

  const badMcp = await httpRpc('tools/list', {}, `Bearer ${BAD_KEY}`)
  expect(badMcp.error, 'zły klucz /mcp: błąd JSON-RPC').toBeDefined()
  expect(badMcp.error!.message, 'komunikat zawiera Unauthorized').toContain('Unauthorized')

  const session = await SseMcp.connect(`Bearer ${BAD_KEY}`)
  try {
    const sseInit = await session.request('initialize', {
      protocolVersion: '2025-11-25',
      capabilities: {},
      clientInfo: { name: 'wd-e2e-real-mcp', version: '0.0.0' },
    })
    expect(sseInit.error, 'SSE initialize ze złym kluczem przechodzi').toBeUndefined()
    await session.initialized()
    const badSse = await session.request('tools/list', {})
    expect(badSse.error, 'zły klucz /sse: błąd JSON-RPC').toBeDefined()
    expect(badSse.error!.message, 'SSE komunikat zawiera Unauthorized').toContain('Unauthorized')
  } finally {
    await session.close()
  }
})

test('SC-E6-2-07: 20 równoległych retrievalli poprawnych; RSS usługi mcp < 256 MB', async ({
  request,
}) => {
  test.setTimeout(600_000)
  expect(PROJECT, 'nazwa projektu compose (WD_CI_PROJECT)').not.toBe('')
  const data = await prepare(request)

  const outcomes = await Promise.all(
    Array.from({ length: PARALLEL_CALLS }, () =>
      httpRpc(
        'tools/call',
        { name: 'ragflow_retrieval', arguments: { question: data.question } },
        `Bearer ${data.keyA}`,
      ),
    ),
  )
  expect(outcomes.length, 'liczba odpowiedzi').toBe(PARALLEL_CALLS)
  outcomes.forEach((outcome, index) => {
    expect(outcome.error, `odpowiedź ${index}: brak błędu JSON-RPC`).toBeUndefined()
    expect(retrievalChunks(outcome).length, `odpowiedź ${index}: fragmenty obecne`).toBeGreaterThan(
      0,
    )
  })
  expect(
    outcomes.some((outcome) => callText(outcome).includes(data.marker)),
    'odpowiedzi niosą treść dokumentu A',
  ).toBe(true)

  // RSS kontenera usługi mcp (wzór: helpers/worker.containerStats dla workera).
  const cid = serviceContainerId(PROJECT, 'mcp')
  expect(cid, 'kontener usługi mcp działa (profil mcp)').not.toBeNull()
  const stats = await containerStats(cid!)
  expect(stats, 'odczyt docker stats dla mcp').not.toBeNull()
  const rssMb = stats!.mem_bytes / 1024 / 1024
  expect(
    stats!.mem_bytes,
    `RSS mcp ${rssMb.toFixed(1)} MB < limit ${RSS_LIMIT_BYTES / 1024 / 1024} MB`,
  ).toBeLessThan(RSS_LIMIT_BYTES)
})
