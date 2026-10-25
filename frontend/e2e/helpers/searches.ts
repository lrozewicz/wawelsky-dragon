// Pomocniki scenariusza S6-12 (kontrakt WP E4-4b §7): sprzątanie wyszukiwarek po biegu. Kopertę
// RAGFlow rozpakowujemy tak samo jak `e2e/helpers.ts` (HTTP 200 + `code 0`).
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

export type CreateSearchOptions = {
  name: string
  /** Bazy wiedzy do podpięcia; idą w `search_config.kb_ids` (§D1) — wiązane w `search_datasets`. */
  datasetIds?: string[]
}

/**
 * Tworzy wyszukiwarkę przez API (wzór `createChat` w `e2e/helpers.ts`). Zwraca jej id.
 * Trasa przyjmuje wiązania baz w ciele `search_config.kb_ids` — osobnego pola `dataset_ids`
 * nie ma (serwis wyciąga je z konfiguracji: `app/services/searches.py`, §D1).
 */
export async function createSearch(
  request: APIRequestContext,
  token: string,
  options: CreateSearchOptions,
): Promise<string> {
  const search = await ok<{ search_id: string }>(
    request.post(apiUrl('/api/v1/searches'), {
      headers: { authorization: `Bearer ${token}` },
      data: {
        name: options.name,
        ...(options.datasetIds === undefined
          ? {}
          : { search_config: { kb_ids: options.datasetIds } }),
      },
    }),
    'POST /api/v1/searches',
  )
  return search.search_id
}

/**
 * Usuwa wszystkie wyszukiwarki tenantu — sprzątanie po scenariuszu. Lista `/searches` startuje
 * z pustego stanu, a reset K9 biegnie raz, przed całym biegiem (jak `deleteAllChats`).
 */
export async function deleteAllSearches(request: APIRequestContext, token: string): Promise<void> {
  const headers = { authorization: `Bearer ${token}` }
  const listed = await ok<{ search_apps: { id: string }[] }>(
    request.get(apiUrl('/api/v1/searches'), { headers }),
    'GET /api/v1/searches',
  )
  for (const search of listed.search_apps) {
    await ok<boolean>(
      request.delete(apiUrl(`/api/v1/searches/${search.id}`), { headers }),
      'DELETE /api/v1/searches/{id}',
    )
  }
}
