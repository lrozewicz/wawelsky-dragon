// Pomocnik scenariusza S6-09 (brief WP E3-6c1/T7): żądanie bez ciasteczek sesji, z samym kluczem
// w nagłówku. `ok` nie jest eksportowane z `../helpers`, więc mamy tu jego kopię w wariancie dla
// wyniku `bearerGet` — koperta RAGFlow: HTTP 200 i `code: 0` (kontrakt E3-6c1 §0).
import { expect, request as playwrightRequest } from '@playwright/test'
import type { APIRequestContext } from '@playwright/test'

const API_URL = process.env.WD_E2E_API_URL ?? ''

type Envelope<T> = { code: number; message: string; data: T }

/** Wynik `bearerGet`: status HTTP i rozwinięta koperta (`null`, gdy odpowiedź bez ciała). */
export type BearerResult = { status: number; envelope: Envelope<unknown> | null }

/** Rozwija kopertę RAGFlow: HTTP 200 + `code 0`, inaczej `expect` rzuca z opisem trasy. */
export function ok<T>(result: BearerResult, label: string): T {
  const message = result.envelope?.message ?? ''
  expect(result.status, `${label}: HTTP ${result.status} — ${message}`).toBe(200)
  expect(result.envelope?.code, `${label}: ${message}`).toBe(0)
  return result.envelope?.data as T
}

/**
 * `GET path` z nagłówkiem `Authorization: Bearer <token>` w ŚWIEŻYM kontekście API — bez
 * ciasteczek przeglądarki (brief pkt 4), więc sukces dowodzi, że działa sam klucz. Ciało
 * czytamy w tym samym kontekście (po `dispose()` odpowiedź jest już niedostępna).
 */
export async function bearerGet(token: string, path: string): Promise<BearerResult> {
  expect(API_URL, 'brak WD_E2E_API_URL — uruchom scenariusz przez `bun run e2e`').not.toBe('')
  const context = await playwrightRequest.newContext()
  try {
    const response = await context.get(`${API_URL}${path}`, {
      headers: { Authorization: `Bearer ${token}` },
    })
    const text = await response.text()
    return {
      status: response.status(),
      envelope: text === '' ? null : (JSON.parse(text) as Envelope<unknown>),
    }
  } finally {
    await context.dispose()
  }
}

/**
 * Maska tokenu na liście kluczy (jak `maskToken` w `features/settings/queries.ts`):
 * pierwsze 12 znaków + `…` + ostatnie 4 — wiersz klucza bez nazwy znajdujemy po masce.
 */
export function maskToken(token: string): string {
  return `${token.slice(0, 12)}…${token.slice(-4)}`
}

/**
 * `DELETE /api/v1/system/tokens/{token}` sesyjnym tokenem dostępu — sprzątanie kluczy API
 * utworzonych w scenariuszu (trasa jak w kroku D `s09-settings-apikeys.spec.ts`).
 */
export async function deleteApiToken(
  request: APIRequestContext,
  sessionToken: string,
  token: string,
): Promise<void> {
  expect(API_URL, 'brak WD_E2E_API_URL — uruchom scenariusz przez `bun run e2e`').not.toBe('')
  const response = await request.delete(`${API_URL}/api/v1/system/tokens/${token}`, {
    headers: { authorization: `Bearer ${sessionToken}` },
  })
  expect(response.status(), 'DELETE /api/v1/system/tokens/{token}').toBe(200)
}
