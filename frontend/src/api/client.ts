/**
 * Klient API (08 §5, §9): openapi-fetch nad `baseUrl = window.location.origin`, z ciasteczkową
 * sesją (`credentials: 'include'`) i middleware, który dokłada Bearer/Accept-Language oraz
 * obsługuje 401 przez JEDNO współdzielone odświeżenie sesji i powtórzenie żądania.
 */

import createClient from 'openapi-fetch'
import type { Client, Middleware } from 'openapi-fetch'

import {
  clearAccessToken,
  getAccessToken,
  setAccessToken,
  setRefreshCallback,
} from '../features/auth/tokenStore'
import { i18n } from '../i18n'
import { unwrap, unwrapEnvelope } from './envelope'
import type { paths } from './schema.gen'

/** Adresy bez Bearera: logowanie i odświeżanie nie mają jeszcze (ważnego) access tokenu. */
const NO_BEARER_PATHS = new Set(['/api/v1/auth/login', '/api/v1/auth/refresh'])
/** Ścieżki auth nie podlegają auto-odświeżaniu (401 z nich to nie wygasła sesja). */
const AUTH_PATH_PREFIX = '/api/v1/auth/'

export const api: Client<paths> = createClient<paths>({
  baseUrl: window.location.origin,
  credentials: 'include',
  // Leniwy wrapper: MSW podmienia `globalThis.fetch` dopiero w `server.listen()`, czyli PO
  // imporcie tego modułu — referencja złapana przy `createClient` ominęłaby interceptory.
  fetch: (input) => globalThis.fetch(input),
})

// Klon żądania sprzed użycia ciała (po `fetch` klonowanie POST-a już się nie uda) — klucz to
// Request, który trafi do `onResponse`, czyli ten zwrócony z `onRequest`.
const retryRequests = new WeakMap<Request, Request>()

let sessionExpiredHandler: (() => void) | null = null
let refreshPromise: Promise<string | null> | null = null

export function setSessionExpiredHandler(fn: (() => void) | null): void {
  sessionExpiredHandler = fn
}

/** Wywołanie handlera wygaśnięcia sesji (używa go też upload.ts, bo nie przechodzi przez middleware). */
export function notifySessionExpired(): void {
  if (sessionExpiredHandler) sessionExpiredHandler()
}

async function performRefresh(): Promise<string | null> {
  try {
    const { data, error, response } = await api.POST('/api/v1/auth/refresh')
    if (!response.ok) {
      clearAccessToken()
      return null
    }

    const payload = unwrapEnvelope<{ access_token?: unknown }>(data ?? error, response.status)
    const token = payload?.access_token
    if (typeof token !== 'string' || token === '') {
      clearAccessToken()
      return null
    }

    setAccessToken(token)
    return token
  } catch {
    // Błąd transportu lub koperta `code ≠ 0` — sesja jest nieważna.
    clearAccessToken()
    return null
  }
}

/** Współdzielone odświeżenie: równoległe 401 czekają na ten sam Promise i widzą jeden refresh. */
export function refreshSession(): Promise<string | null> {
  refreshPromise ??= performRefresh().finally(() => {
    refreshPromise = null
  })
  return refreshPromise
}

const middleware: Middleware = {
  onRequest({ request }) {
    const pathname = new URL(request.url).pathname
    const headers = new Headers(request.headers)
    const token = getAccessToken()

    if (token !== null && !NO_BEARER_PATHS.has(pathname)) {
      headers.set('Authorization', `Bearer ${token}`)
    }
    headers.set('Accept-Language', i18n.language)

    const retrySource = request.clone()
    const next = new Request(request, { headers })
    retryRequests.set(next, retrySource)
    return next
  },

  async onResponse({ request, response, options }) {
    if (response.status !== 401) return
    if (new URL(request.url).pathname.startsWith(AUTH_PATH_PREFIX)) return

    const token = await refreshSession()
    if (token === null) {
      notifySessionExpired()
      return
    }

    // Klon z `onRequest` zawsze istnieje dla żądania, które przeszło przez middleware.
    const retrySource = retryRequests.get(request)!
    const headers = new Headers(retrySource.headers)
    headers.set('Authorization', `Bearer ${token}`)
    // Powtórzenie musi nieść te same nagłówki kontekstowe co oryginał (klon ich nie ma).
    headers.set('Accept-Language', i18n.language)
    const retried = await options.fetch(new Request(retrySource, { headers }))

    if (retried.status === 401) {
      notifySessionExpired()
    }
    return retried
  },
}

api.use(middleware)

// Proaktywny refresh z tokenStore woła dokładnie tę samą, współdzieloną ścieżkę.
setRefreshCallback(refreshSession)

/** Rozpakowanie koperty z wyniku openapi-fetch (`{data, error, response}`) — patrz envelope.ts. */
export function apiCall<T>(
  promise: Promise<{ data?: unknown; error?: unknown; response: Response }>,
): Promise<T> {
  return promise.then((result) => unwrap<T>(result))
}
