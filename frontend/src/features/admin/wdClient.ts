/**
 * Klient tras administracyjnych WD (`/api/wd/v1/...`, kontrakt WP E3-6c2 §1).
 * Koperta wd różni się od RAGFlow: sukces to `{data}` bez pola `code`, 204 bez ciała,
 * a błąd to HTTP 4xx `{error: {code, message}}`. Dlatego NIE używamy `unwrap`
 * z `src/api/envelope.ts` (wymaga `code: number`) — rozpakowanie jest tutaj.
 */

export class WdApiError extends Error {
  constructor(
    public readonly code: string,
    message: string,
    public readonly httpStatus: number,
    /** `error.details` z ciała błędu (K3 §3 p. 4), gdy jest obiektem — opcjonalne, dodatkowe pola. */
    public readonly details?: Record<string, unknown>,
  ) {
    super(message)
    this.name = 'WdApiError'
  }
}

/** Slugi błędów WD (kontrakt §0) — dla nich istnieje tłumaczenie `admin.error.<slug>`. */
export const WD_ERROR_SLUGS: readonly string[] = [
  'validation_failed',
  'not_found',
  'conflict',
  'permission_denied',
  'unauthorized',
  'authentication_failed',
  'operation_not_allowed',
  'upstream_error',
  'busy',
  'rate_limited',
]

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
}

/**
 * Rozpakowuje wynik openapi-fetch dla tras wd. `!response.ok` → `WdApiError`
 * (kod i komunikat z ciała błędu, z fallbackiem `unknown`/`statusText`).
 * Sukces: 204 → `undefined`, inaczej `data.data`.
 */
export function wdCall<T>(
  promise: Promise<{ data?: unknown; error?: unknown; response: Response }>,
): Promise<T> {
  return promise.then(({ data, error, response }) => {
    if (!response.ok) {
      const body = isRecord(error) && isRecord(error.error) ? error.error : {}
      const code = typeof body.code === 'string' ? body.code : 'unknown'
      const message = typeof body.message === 'string' ? body.message : response.statusText
      // `details` (np. `task_id`, `received_bytes`, `suggested_name`) dochodzi tylko, gdy jest obiektem.
      const details = isRecord(body.details) ? body.details : undefined
      throw new WdApiError(code, message, response.status, details)
    }
    if (response.status === 204) return undefined as T
    return (data as { data: T }).data
  })
}

/** Klucz i18n komunikatu błędu: `admin.error.<slug>` dla znanego sluga, inaczej `admin.error.unknown`. */
export function wdErrorKey(err: unknown): string {
  if (err instanceof WdApiError && WD_ERROR_SLUGS.includes(err.code)) {
    return `admin.error.${err.code}`
  }
  return 'admin.error.unknown'
}
