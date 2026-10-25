/**
 * Kształty list RAGFlow per endpoint (02-api.md §6.1) — każdy profil parsowany osobno.
 * `body` to PEŁNE ciało koperty (`{code,message,data,…top}`), bo część endpointów trzyma
 * total na najwyższym poziomie (`total_datasets`).
 */
import { ApiError, type Envelope } from './envelope'

export type ListEndpoint = 'datasets' | 'documents' | 'chunks' | 'chats' | 'sessions'

export type ListResult<T> = { items: T[]; total: number; doc?: unknown }

function shapeError(endpoint: ListEndpoint, httpStatus: number): ApiError {
  return new ApiError(-1, `Nieprawidłowy kształt listy: ${endpoint}`, httpStatus)
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
}

/** `total` z obiektu listy; brak liczby → długość tablicy. */
function totalOf(record: Record<string, unknown>, items: unknown[]): number {
  return typeof record.total === 'number' ? record.total : items.length
}

export function unwrapList<T = unknown>(
  endpoint: ListEndpoint,
  body: unknown,
  httpStatus = 200,
): ListResult<T> {
  if (!isRecord(body) || typeof body.code !== 'number') {
    throw shapeError(endpoint, httpStatus)
  }
  const envelope = body as Envelope<unknown>
  if (envelope.code !== 0) {
    throw new ApiError(envelope.code, envelope.message ?? '', httpStatus)
  }
  const data = envelope.data
  switch (endpoint) {
    case 'datasets': {
      if (!Array.isArray(data)) throw shapeError(endpoint, httpStatus)
      const total = typeof body.total_datasets === 'number' ? body.total_datasets : data.length
      return { items: data as T[], total }
    }
    case 'sessions': {
      if (!Array.isArray(data)) throw shapeError(endpoint, httpStatus)
      return { items: data as T[], total: data.length }
    }
    case 'documents': {
      if (!isRecord(data) || !Array.isArray(data.docs)) throw shapeError(endpoint, httpStatus)
      return { items: data.docs as T[], total: totalOf(data, data.docs) }
    }
    case 'chunks': {
      if (!isRecord(data) || !Array.isArray(data.chunks)) throw shapeError(endpoint, httpStatus)
      return { items: data.chunks as T[], total: totalOf(data, data.chunks), doc: data.doc }
    }
    case 'chats': {
      if (Array.isArray(data)) return { items: data as T[], total: data.length }
      if (isRecord(data) && Array.isArray(data.chats)) {
        return { items: data.chats as T[], total: totalOf(data, data.chats) }
      }
      throw shapeError(endpoint, httpStatus)
    }
  }
}
