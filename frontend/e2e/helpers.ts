// Pomocniki API wspólne dla scenariuszy S6-07 i S6-08 (kontrakt WP E3-5b, T7): logowanie,
// baza wiedzy z jednym sparsowanym dokumentem tekstowym i utworzenie czatu. Wzorzec operacji
// (koperta RAGFlow, upload multipart, odpytywanie do `run = DONE`) z `infra-parse.spec.ts`.
// Scenariusze nie mockują backendu — te same trasy woła UI.
import { ADMIN_EMAIL, ADMIN_PASSWORD, expect } from './fixtures'
import type { APIRequestContext, APIResponse, Page } from '@playwright/test'

const API_URL = process.env.WD_E2E_API_URL ?? ''

/** Limit odpytywania o stan parsowania (jak `infra-parse.spec.ts`). */
export const POLL_TIMEOUT_MS = 90_000
const POLL_INTERVAL_MS = 1_000

const sleep = (ms: number): Promise<void> => new Promise((resolve) => setTimeout(resolve, ms))

type Envelope<T> = { code: number; message: string; data: T }

/** Rozwija kopertę RAGFlow: HTTP 200 + `code 0`, inaczej `expect` rzuca z opisem trasy. */
async function ok<T>(pending: Promise<APIResponse>, label: string): Promise<T> {
  const response = await pending
  const body = (await response.json()) as Envelope<T>
  expect(response.status(), `${label}: HTTP ${response.status()} — ${body.message}`).toBe(200)
  expect(body.code, `${label}: ${body.message}`).toBe(0)
  return body.data
}

/** Logowanie kontem z seedu K9 przez UI (jak S6-01, S6-02 i S6-06). */
export async function loginViaUi(page: Page): Promise<void> {
  await page.goto('/')
  await page.getByTestId('login-email').fill(ADMIN_EMAIL)
  await page.getByTestId('login-password').fill(ADMIN_PASSWORD)
  await page.getByTestId('login-submit').click()
  await expect(page.getByTestId('home-banner')).toBeVisible()
}

/** Logowanie przez API; token idzie potem w nagłówku `Authorization`. */
export async function apiLogin(request: APIRequestContext): Promise<string> {
  expect(API_URL, 'brak WD_E2E_API_URL — uruchom scenariusz przez `bun run e2e`').not.toBe('')
  const data = await ok<{ access_token: string }>(
    request.post(`${API_URL}/api/v1/auth/login`, {
      data: { email: ADMIN_EMAIL, password: ADMIN_PASSWORD },
    }),
    'POST /api/v1/auth/login',
  )
  return data.access_token
}

export type SeededCorpus = { datasetId: string; documentId: string; documentName: string }

export type SeedOptions = {
  /** Nazwa bazy wiedzy; musi być unikalna w obrębie scenariusza (reset K9 czyści bazę). */
  datasetName: string
  documentName: string
  /** Treść dokumentu — pytanie w scenariuszu musi zawierać jego słowa (retrieval). */
  documentBody: string
}

/**
 * Tworzy bazę wiedzy, wgrywa dokument tekstowy i czeka (do 90 s) na `run = DONE` workera.
 * Zwraca identyfikatory potrzebne do utworzenia czatu.
 */
export async function seedCorpus(
  request: APIRequestContext,
  token: string,
  options: SeedOptions,
): Promise<SeededCorpus> {
  const headers = { authorization: `Bearer ${token}` }
  const dataset = await ok<{ id: string }>(
    request.post(`${API_URL}/api/v1/datasets`, {
      headers,
      data: { name: options.datasetName },
    }),
    'POST /api/v1/datasets',
  )

  const uploaded = await ok<{ id: string }[]>(
    request.post(`${API_URL}/api/v1/datasets/${dataset.id}/documents`, {
      headers,
      multipart: {
        file: {
          name: options.documentName,
          mimeType: 'text/plain',
          buffer: Buffer.from(options.documentBody, 'utf-8'),
        },
      },
    }),
    'POST /api/v1/datasets/{id}/documents',
  )
  expect(uploaded, 'upload zwrócił dokładnie jeden dokument').toHaveLength(1)
  // `noUncheckedIndexedAccess`: dostęp po asercji długości wymaga `!` (wzór: uploadFiles.ts).
  const documentId = uploaded[0]!.id

  await ok<{ success_count: number }>(
    request.post(`${API_URL}/api/v1/datasets/${dataset.id}/documents/parse`, {
      headers,
      data: { document_ids: [documentId] },
    }),
    'POST /api/v1/datasets/{id}/documents/parse',
  )

  const deadline = Date.now() + POLL_TIMEOUT_MS
  let run = ''
  while (Date.now() < deadline) {
    const listed = await ok<{ docs: { run: string; chunk_count: number }[] }>(
      request.get(`${API_URL}/api/v1/datasets/${dataset.id}/documents?id=${documentId}`, {
        headers,
      }),
      'GET /api/v1/datasets/{id}/documents',
    )
    run = listed.docs[0]?.run ?? ''
    if (run === 'DONE' || run === 'FAIL' || run === 'CANCEL') break
    await sleep(POLL_INTERVAL_MS)
  }
  expect(run, 'stan parsowania dokumentu').toBe('DONE')

  return { datasetId: dataset.id, documentId, documentName: options.documentName }
}

/**
 * Tworzy bazę wiedzy bez dokumentów (kontrakt §T6: drugi dataset S6-06 ma `chunk_count = 0`,
 * więc model embeddingu jest w konfiguracji odblokowany). Zwraca jej id.
 */
export async function createDataset(
  request: APIRequestContext,
  token: string,
  name: string,
): Promise<string> {
  const dataset = await ok<{ id: string }>(
    request.post(`${API_URL}/api/v1/datasets`, {
      headers: { authorization: `Bearer ${token}` },
      data: { name },
    }),
    'POST /api/v1/datasets',
  )
  return dataset.id
}

export type CreateChatOptions = {
  name: string
  datasetIds?: string[]
  /** Identyfikator modelu z rejestru (`GET /api/v1/models`), np. model `fake-chat-think`. */
  llmId?: string
}

/**
 * Usuwa wszystkie czaty tenantu — sprzątanie po scenariuszu. `s07a-chats-list.spec.ts` zakłada
 * PUSTĄ listę czatów (pusty stan), a reset bazy K9 biegnie raz, przed całym biegiem.
 */
export async function deleteAllChats(request: APIRequestContext, token: string): Promise<void> {
  const headers = { authorization: `Bearer ${token}` }
  const listed = await ok<{ chats: { id: string }[] }>(
    request.get(`${API_URL}/api/v1/chats`, { headers }),
    'GET /api/v1/chats',
  )
  const ids = listed.chats.map((chat) => chat.id)
  if (ids.length === 0) return
  await ok<{ success_count: number }>(
    request.delete(`${API_URL}/api/v1/chats`, { headers, data: { ids } }),
    'DELETE /api/v1/chats',
  )
}

/** Tworzy czat przez API (kontrakt §T7: S6-08 używa API zamiast UI). Zwraca jego id. */
export async function createChat(
  request: APIRequestContext,
  token: string,
  options: CreateChatOptions,
): Promise<string> {
  const chat = await ok<{ id: string }>(
    request.post(`${API_URL}/api/v1/chats`, {
      headers: { authorization: `Bearer ${token}` },
      data: {
        name: options.name,
        dataset_ids: options.datasetIds ?? [],
        ...(options.llmId === undefined ? {} : { llm_id: options.llmId }),
      },
    }),
    'POST /api/v1/chats',
  )
  return chat.id
}
