/**
 * Koperta RAGFlow `{code, message, data}` (backend/app/api/ragflow/envelope.py).
 * Backend zwraca HTTP 200 także dla błędów biznesowych (`code !== 0`), dlatego `code`
 * sprawdzamy zawsze, a nie tylko przy `!response.ok` (08 §9.1).
 */

export class ApiError extends Error {
  constructor(
    public readonly code: number,
    message: string,
    public readonly httpStatus: number,
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

export type Envelope<T> = { code: number; message?: string; data?: T }

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
}

/** Część wspólna reguł (2)–(4): samo ciało koperty plus status HTTP (używane też przez refresh/upload). */
export function unwrapEnvelope<T>(body: unknown, httpStatus: number): T {
  if (!isRecord(body) || typeof body.code !== 'number') {
    throw new ApiError(-1, 'Nieprawidłowa odpowiedź serwera', httpStatus)
  }
  const envelope = body as Envelope<T>
  if (envelope.code !== 0) {
    throw new ApiError(envelope.code, envelope.message ?? '', httpStatus)
  }
  return envelope.data as T
}

/** `result` to zwrot openapi-fetch: sukces w `data`, błąd transportu w `error`. */
export function unwrap<T>(result: { data?: unknown; error?: unknown; response: Response }): T {
  const { data, error, response } = result
  if (!response.ok) {
    const failure = isRecord(error) ? error : {}
    const code = typeof failure.code === 'number' ? failure.code : response.status
    const message = typeof failure.message === 'string' ? failure.message : response.statusText
    throw new ApiError(code, message, response.status)
  }
  return unwrapEnvelope<T>(data, response.status)
}
