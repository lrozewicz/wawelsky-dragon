// Scenariusz infrastrukturalny (brief E3-5a T1): w stosie testowym `api` i `worker` współdzielą
// zapisywalny wolumen `/data` (DEC-070), więc dokument wgrany przez API jest parsowany przez
// workera do `run = DONE` z `chunk_count > 0`. Bez UI — samo `request` Playwrighta.
import { ADMIN_EMAIL, ADMIN_PASSWORD, expect, test } from './fixtures'
import type { APIRequestContext, APIResponse } from '@playwright/test'

const API_URL = process.env.WD_E2E_API_URL ?? ''
const POLL_TIMEOUT_MS = 90_000
const POLL_INTERVAL_MS = 1_000

const DOCUMENT_NAME = 'e2e-infra-parse.txt'
const DOCUMENT_BODY = [
  'Wawelsky Dragon — dokument kontrolny stosu testowego.',
  '',
  'Smok pilnuje zbocza Wawelu, a katalog /data dziela api i worker.',
  '',
].join('\n')

type Envelope<T> = { code: number; message: string; data: T }
type Dataset = { id: string }
type DocumentState = { id: string; run: string; chunk_count: number; progress_msg: string }

const sleep = (ms: number): Promise<void> => new Promise((resolve) => setTimeout(resolve, ms))

/** Rozwija kopertę RAGFlow: HTTP 200 + `code 0`, inaczej `expect` rzuca z opisem trasy. */
async function ok<T>(pending: Promise<APIResponse>, label: string): Promise<T> {
  const response = await pending
  const body = (await response.json()) as Envelope<T>
  expect(response.status(), `${label}: HTTP ${response.status()} — ${body.message}`).toBe(200)
  expect(body.code, `${label}: ${body.message}`).toBe(0)
  return body.data
}

/** Logowanie przez API; token z `data.access_token` idzie potem w nagłówku `Authorization`. */
async function login(request: APIRequestContext): Promise<string> {
  const data = await ok<{ access_token: string }>(
    request.post(`${API_URL}/api/v1/auth/login`, {
      data: { email: ADMIN_EMAIL, password: ADMIN_PASSWORD },
    }),
    'POST /api/v1/auth/login',
  )
  return data.access_token
}

test('worker parsuje dokument wgrany przez API (wspólne /data)', async ({ request }) => {
  // 90 s pętli odpytywania plus narzut na logowanie, upload i kompilację listy.
  test.setTimeout(120_000)
  expect(API_URL, 'brak WD_E2E_API_URL — uruchom scenariusz przez `bun run e2e`').not.toBe('')

  const token = await login(request)
  const headers = { authorization: `Bearer ${token}` }

  const dataset = await ok<Dataset>(
    request.post(`${API_URL}/api/v1/datasets`, {
      headers,
      data: { name: 'e2e-infra-parse' },
    }),
    'POST /api/v1/datasets',
  )

  // Multipart: pole `file` (UploadDocumentsForm); API zapisuje bajty do /data/files.
  const uploaded = await ok<DocumentState[]>(
    request.post(`${API_URL}/api/v1/datasets/${dataset.id}/documents`, {
      headers,
      multipart: {
        file: {
          name: DOCUMENT_NAME,
          mimeType: 'text/plain',
          buffer: Buffer.from(DOCUMENT_BODY, 'utf-8'),
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

  // Worker czyta plik z /data/files — bez wspólnego wolumenu zostaje SCHEDULE do timeoutu.
  const deadline = Date.now() + POLL_TIMEOUT_MS
  let state: DocumentState | undefined
  while (Date.now() < deadline) {
    const listed = await ok<{ docs: DocumentState[] }>(
      request.get(`${API_URL}/api/v1/datasets/${dataset.id}/documents?id=${documentId}`, {
        headers,
      }),
      'GET /api/v1/datasets/{id}/documents',
    )
    state = listed.docs[0]
    if (state === undefined || state.run === 'DONE' || state.run === 'FAIL') break
    if (state.run === 'CANCEL') break
    await sleep(POLL_INTERVAL_MS)
  }

  expect(state?.run, `run dokumentu (progress: ${state?.progress_msg ?? 'brak'})`).toBe('DONE')
  expect(state?.chunk_count ?? 0, 'chunk_count dokumentu').toBeGreaterThan(0)
})
