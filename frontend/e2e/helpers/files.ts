// Pomocniki scenariusza S6-13 (kontrakt WP E4-5c §8): sprzątanie menedżera plików i datasetu po
// biegu. Kopertę RAGFlow rozpakowujemy tak samo jak `e2e/helpers.ts` (HTTP 200 + `code 0`);
// bez surowego `curl`.
import type { APIRequestContext, APIResponse } from '@playwright/test'

import { expect } from '../fixtures'

const API_URL = process.env.WD_E2E_API_URL ?? ''

type Envelope<T> = { code: number; message: string; data: T }

/** Adres API z walidacją zmiennej harnessu (jak `apiLogin` w `e2e/helpers.ts`). */
function apiUrl(path: string): string {
  expect(API_URL, 'brak WD_E2E_API_URL — uruchom scenariusz przez `bun run e2e`').not.toBe('')
  return `${API_URL}${path}`
}

/** Rozwija kopertę RAGFlow: HTTP 200 + `code 0`, inaczej `expect` rzuca z opisem trasy. */
async function ok<T>(pending: Promise<APIResponse>, label: string): Promise<T> {
  const response = await pending
  const body = (await response.json()) as Envelope<T>
  expect(response.status(), `${label}: HTTP ${response.status()} — ${body.message}`).toBe(200)
  expect(body.code, `${label}: ${body.message}`).toBe(0)
  return body.data
}

/**
 * Usuwa wszystkie wiersze widoczne w rootcie menedżera plików — sprzątanie po scenariuszu.
 * Root znamy z `GET /api/v1/files` bez `parent_id`; `page_size` z zapasem, by objąć wszystkie
 * wiersze (folder rekurencyjnie kasuje zawartość, DEC-188).
 */
export async function deleteAllFiles(request: APIRequestContext, token: string): Promise<void> {
  const headers = { authorization: `Bearer ${token}` }
  const listed = await ok<{ files: { id: string }[] }>(
    request.get(apiUrl('/api/v1/files?page=1&page_size=1000'), { headers }),
    'GET /api/v1/files',
  )
  const ids = listed.files.map((file) => file.id)
  if (ids.length === 0) return
  await ok<{ success_count: number }>(
    request.delete(apiUrl('/api/v1/files'), { headers, data: { ids } }),
    'DELETE /api/v1/files',
  )
}

/** Usuwa dataset utworzony przez scenariusz (razem ze zlinkowanymi dokumentami). */
export async function deleteDataset(
  request: APIRequestContext,
  token: string,
  datasetId: string,
): Promise<void> {
  await ok<{ success_count: number }>(
    request.delete(apiUrl('/api/v1/datasets'), {
      headers: { authorization: `Bearer ${token}` },
      data: { ids: [datasetId] },
    }),
    'DELETE /api/v1/datasets',
  )
}
