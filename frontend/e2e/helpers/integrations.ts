// Pomocniki scenariusza S6-11 (brief WP E4-3c/T5, rozszerzone w E4-3d/T5): lista i czyszczenie
// integracji przez API WD, odpytywanie stanu przebiegu (sync), licznik dokumentów datasetu przez
// API RAGFlow oraz strażnik błędów konsoli z wąskim wyjątkiem na oczekiwany 400 z zapisu
// (wariant „zły sekret" — DEC-152; pełny cykl na stubie Graph opisuje DEC-183). `ok` RAGFlow nie
// jest eksportowane z `../helpers`, więc dla tras WD mamy tu jego kopię w wariancie dla koperty
// `{data}`/204 (kontrakt E4-3c §0), a dla rozliczeń dokumentów — wariant koperty RAGFlow.
// Stos e2e jest współdzielony między scenariuszami, więc scenariusz startuje od pustej listy
// integracji.
import { expect } from '@playwright/test'
import type { APIRequestContext, APIResponse, ConsoleMessage, Page } from '@playwright/test'

const API_URL = process.env.WD_E2E_API_URL ?? ''

/** Rozmiar strony listy integracji — zgodny z `INTEGRATIONS_PAGE_SIZE` kontraktu §1. */
const PAGE_SIZE = 100

/** Odstęp między próbami odpytywania stanu przebiegu (sync ≤ 120 s — brief T5 p. 5). */
const POLL_INTERVAL_MS = 1_000

const sleep = (ms: number): Promise<void> => new Promise((resolve) => setTimeout(resolve, ms))

type WdEnvelope<T> = { data: T }

type RagflowEnvelope<T> = { code: number; message: string; data: T }

/** Wiersz listy integracji; scenariusz potrzebuje identyfikatora i nazwy. */
export type WdIntegrationRow = { id: number; name: string }

/** Stan integracji z `GET /integrations/{id}/status` (pola potrzebne do pilnowania przebiegu). */
export type WdIntegrationStatus = {
  is_running: boolean
  last_sync_status: string | null
  latest_run: { id: number; status: string; added: number; failed: number } | null
}

/** Stany przebiegu, w których synchronizacja jeszcze trwa (kontrakt E4-3c §0). */
const ACTIVE_RUN_STATUSES = new Set(['running', 'queued'])

/**
 * Sprawdza status odpowiedzi trasy wd i rozwija jej kopertę. Ciało czytamy raz (`text()`),
 * bo komunikat błędu nie może użyć strumienia przed `JSON.parse`; 204 ciała nie ma.
 */
async function ok<T>(
  pending: Promise<APIResponse>,
  label: string,
  expectedStatus = 200,
): Promise<T> {
  const response = await pending
  const text = await response.text()
  expect(response.status(), `${label}: HTTP ${response.status()} — ${text}`).toBe(expectedStatus)
  if (expectedStatus === 204) return undefined as unknown as T
  return (JSON.parse(text) as WdEnvelope<T>).data
}

/** Pierwsza strona listy integracji (`GET /api/wd/v1/integrations`). */
export async function listIntegrations(
  request: APIRequestContext,
  token: string,
): Promise<WdIntegrationRow[]> {
  const listed = await ok<{ items: WdIntegrationRow[] }>(
    request.get(`${API_URL}/api/wd/v1/integrations?page=1&page_size=${PAGE_SIZE}`, {
      headers: { authorization: `Bearer ${token}` },
    }),
    'GET /api/wd/v1/integrations',
  )
  return listed.items
}

/**
 * Usuwa wszystkie integracje tenantu (`DELETE` po id, odpowiedź 204) — sprzątanie scenariusza.
 * Po usunięciu pierwszej strony pobieramy `page=1` ponownie, aż lista będzie pusta — inaczej
 * integracje spoza pierwszych `PAGE_SIZE` pozycji zostałyby na stosie.
 */
export async function deleteAllIntegrations(
  request: APIRequestContext,
  token: string,
): Promise<void> {
  const headers = { authorization: `Bearer ${token}` }
  let rows = await listIntegrations(request, token)
  while (rows.length > 0) {
    for (const row of rows) {
      await ok<undefined>(
        request.delete(`${API_URL}/api/wd/v1/integrations/${row.id}`, { headers }),
        `DELETE /api/wd/v1/integrations/${row.id}`,
        204,
      )
    }
    rows = await listIntegrations(request, token)
  }
}

/** Stan integracji (`GET /api/wd/v1/integrations/{id}/status`). */
export async function integrationStatus(
  request: APIRequestContext,
  token: string,
  id: number,
): Promise<WdIntegrationStatus> {
  return ok<WdIntegrationStatus>(
    request.get(`${API_URL}/api/wd/v1/integrations/${id}/status`, {
      headers: { authorization: `Bearer ${token}` },
    }),
    `GET /api/wd/v1/integrations/${id}/status`,
  )
}

/**
 * Czeka (do `timeoutMs`, domyślnie 120 s) na zakończenie najnowszego przebiegu i zwraca stan.
 * Warunek końca wymaga obecnego `latest_run` w stanie terminalnym — inaczej pierwsze odpytywanie
 * tuż po zleceniu (przed wstawieniem wiersza runu) uznałoby przebieg za zakończony.
 */
export async function pollRunFinished(
  request: APIRequestContext,
  token: string,
  id: number,
  timeoutMs = 120_000,
): Promise<WdIntegrationStatus> {
  const deadline = Date.now() + timeoutMs
  for (;;) {
    const status = await integrationStatus(request, token, id)
    if (
      !status.is_running &&
      status.latest_run !== null &&
      !ACTIVE_RUN_STATUSES.has(status.latest_run.status)
    ) {
      return status
    }
    expect(
      Date.now(),
      `przebieg integracji ${id} nie zakończył się w ${timeoutMs / 1000} s`,
    ).toBeLessThan(deadline)
    await sleep(POLL_INTERVAL_MS)
  }
}

/**
 * Nazwy dokumentów datasetu docelowego (`GET /api/v1/datasets/{id}/documents`) — licznik 3/4
 * z briefu T5 wymaga nazw, nie tylko `total`. Koperta RAGFlow: HTTP 200 + `code 0`.
 */
export async function listDatasetDocuments(
  request: APIRequestContext,
  token: string,
  datasetId: string,
): Promise<string[]> {
  const response = await request.get(
    `${API_URL}/api/v1/datasets/${datasetId}/documents?page=1&page_size=${PAGE_SIZE}`,
    { headers: { authorization: `Bearer ${token}` } },
  )
  const text = await response.text()
  expect(
    response.status(),
    `GET /api/v1/datasets/${datasetId}/documents: HTTP ${response.status()} — ${text}`,
  ).toBe(200)
  const body = JSON.parse(text) as RagflowEnvelope<{ docs: { name: string }[] }>
  expect(body.code, `GET /api/v1/datasets/${datasetId}/documents: ${body.message}`).toBe(0)
  return body.data.docs.map((doc) => doc.name)
}

// 401 z `/api/v1/auth/refresh` to oczekiwany stan „brak sesji" (08 §5.3) — ten sam filtr,
// co w strażniku fixture `page` (`../fixtures.ts`).
function isExpectedRefresh401(message: ConsoleMessage): boolean {
  return message.text().includes('401') && message.location().url.includes('/api/v1/auth/refresh')
}

/**
 * Oczekiwany 400 z zapisu integracji przy złym sekrecie (DEC-152). Wąsko: tylko odpowiedź
 * błędu 400 z samego `POST /api/wd/v1/integrations` — lista ma ten samą ścieżkę, ale z query.
 */
function isExpectedCreateWithBadSecret(message: ConsoleMessage): boolean {
  return (
    message.type() === 'error' &&
    message.text().includes('status of 400') &&
    message.location().url.endsWith('/api/wd/v1/integrations')
  )
}

/**
 * Strażnik błędów konsoli scenariusza S6-11. Fixture `page` (`../fixtures.ts`, poza zakresem T5)
 * nie przyjmuje wyjątków, a edycja `fixtures.ts` jest w tym zadaniu zakazana — zdejmujemy więc
 * jego nasłuch konsoli i zakładamy równoważny, z DOKŁADNIE jednym wąskim wyjątkiem: oczekiwanym
 * 400 z zapisu przy złym sekrecie. `expected` to dodatkowe, równie wąskie wyjątki konkretnego
 * wariantu — każdy inny błąd konsoli nadal wywala test. Nasłuch `pageerror` fixture'y zostaje bez
 * zmian. Zwracana tablica jest żywa — scenariusz asertuje ją końcu.
 */
export function takeOverConsoleGuard(
  page: Page,
  expected: readonly ((message: ConsoleMessage) => boolean)[] = [],
): string[] {
  page.removeAllListeners('console')
  const errors: string[] = []
  page.on('console', (message) => {
    if (message.type() !== 'error') return
    if (isExpectedRefresh401(message) || isExpectedCreateWithBadSecret(message)) return
    if (expected.some((allow) => allow(message))) return
    errors.push(`${message.text()} (${message.location().url})`)
  })
  return errors
}
