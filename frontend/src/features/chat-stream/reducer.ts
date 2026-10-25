import type { SseData, SseFrame } from '../../lib/sse'

// Kontrakt WP E3-5a §3: czysty reduktor ramek SSE.
export type Citation = {
  chunkId: string
  docId: string
  docName: string
  content: string
  similarity: number | null
  // Strona chunku wywiedziona z `reference.chunks[i].positions` (`[strona, …]`, 1-based);
  // brak pozycji (np. dokument tekstowy) → pole pominięte (kontrakt WP E5-H3 §Decyzje UX #7).
  page?: number | null
}

export type StreamState = {
  status: 'idle' | 'streaming' | 'done' | 'error'
  mode: 'answer' | 'think'
  thinking: string
  answer: string
  citations: Citation[] // znormalizowane chunki, kolejność = indeks [ID:n]
  docAggs: { docId: string; docName: string; count: number }[]
  sessionId: string | null
  messageId: string | null
  error: string | null
}

export const initialStreamState: StreamState = {
  status: 'idle',
  mode: 'answer',
  thinking: '',
  answer: '',
  citations: [],
  docAggs: [],
  sessionId: null,
  messageId: null,
  error: null,
}

type ChunkInput = unknown[] | Record<string, unknown>

// Pierwsza nazwa z listy, która niesie napis; inaczej pusty napis.
function pickString(record: Record<string, unknown>, keys: string[]): string {
  for (const key of keys) {
    const value = record[key]
    if (typeof value === 'string') return value
  }
  return ''
}

const CHUNK_ID_KEYS = ['id', 'chunk_id']
const CHUNK_DOC_ID_KEYS = ['document_id', 'doc_id']
const CHUNK_DOC_NAME_KEYS = ['document_name', 'docnm_kwd']
const CHUNK_CONTENT_KEYS = ['content', 'content_with_weight']

/**
 * Strona chunku z `positions` RAGFlow (`[strona, lewo, prawo, góra, dół]`; strona 1-based).
 * Brak pozycji (dokument tekstowy) albo wartość niecałkowita/zerowa → `undefined` (pole pominięte).
 */
function chunkPage(record: Record<string, unknown>): number | undefined {
  const positions = record.positions
  if (!Array.isArray(positions) || positions.length === 0) return undefined
  const first = positions[0]
  if (!Array.isArray(first) || first.length === 0) return undefined
  const page = first[0]
  return typeof page === 'number' && Number.isInteger(page) && page > 0 ? page : undefined
}

/** Normalizuje surowe chunki z `reference.chunks` do cytowań (kontrakt §3). */
export function normalizeChunks(raw: ChunkInput): Citation[] {
  const items = Array.isArray(raw) ? raw : Object.values(raw)
  const citations: Citation[] = []
  for (const item of items) {
    if (item === null || typeof item !== 'object') continue
    const record = item as Record<string, unknown>
    const page = chunkPage(record)
    citations.push({
      chunkId: pickString(record, CHUNK_ID_KEYS),
      docId: pickString(record, CHUNK_DOC_ID_KEYS),
      docName: pickString(record, CHUNK_DOC_NAME_KEYS),
      content: pickString(record, CHUNK_CONTENT_KEYS),
      similarity: typeof record.similarity === 'number' ? record.similarity : null,
      ...(page === undefined ? {} : { page }),
    })
  }
  return citations
}

function normalizeDocAggs(raw: unknown[] | undefined): StreamState['docAggs'] {
  if (!Array.isArray(raw)) return []
  const aggs: StreamState['docAggs'] = []
  for (const item of raw) {
    if (item === null || typeof item !== 'object') continue
    const record = item as Record<string, unknown>
    aggs.push({
      docId: typeof record.doc_id === 'string' ? record.doc_id : '',
      docName: typeof record.doc_name === 'string' ? record.doc_name : '',
      count: typeof record.count === 'number' ? record.count : 0,
    })
  }
  return aggs
}

// Ramka błędu może nie nieść `data` (np. `{"code":500,"message":"boom"}`) — wtedy samo `message`.
function errorAnswer(data: unknown): string | undefined {
  if (typeof data !== 'object' || data === null) return undefined
  return (data as SseData).answer
}

// Puste chunki (brak / [] / {}) nie kasują poprzednich cytowań (kontrakt §3).
function hasChunks(chunks: ChunkInput | undefined): chunks is ChunkInput {
  if (chunks === undefined) return false
  if (Array.isArray(chunks)) return chunks.length > 0
  return Object.keys(chunks).length > 0
}

/** Czysty reduktor: ramka SSE → nowy stan (kontrakt §3). */
export function reduce(state: StreamState, frame: SseFrame): StreamState {
  if (state.status === 'done' || state.status === 'error') return state

  if (frame.data === true) return { ...state, status: 'done' }

  const data = frame.data
  if (frame.code !== 0) {
    return {
      ...state,
      status: 'error',
      error: frame.message || errorAnswer(data) || 'error',
    }
  }

  if (data == null) return { ...state, status: 'streaming' }

  let next: StreamState = { ...state, status: 'streaming' }

  // Tryb ustawiamy przed dopisaniem delty (ramka może nieść i tryb, i `answer`).
  let mode: StreamState['mode'] = state.mode
  if (data.start_to_think) mode = 'think'
  if (data.end_to_think) mode = 'answer'
  if (mode !== state.mode) next = { ...next, mode }

  if (typeof data.answer === 'string') {
    if (mode === 'think') {
      next = { ...next, thinking: next.thinking + data.answer }
    } else if (data.final === true && data.answer !== '') {
      // Ścieżka empty_response v0.27 (K4 §1.4): finalna ramka niesie TEN SAM tekst co delta
      // (`final:false`), więc tekst zastępuje zgromadzony — inaczej dubluje się w dymku.
      // Finalna ramka ścieżki zwykłej ma `answer=""` i przechodzi niżej (dopisanie pustego).
      next = { ...next, answer: data.answer }
    } else {
      next = { ...next, answer: next.answer + data.answer }
    }
  }

  const reference = data.reference
  if (reference !== undefined && hasChunks(reference.chunks)) {
    next = {
      ...next,
      citations: normalizeChunks(reference.chunks),
      docAggs: normalizeDocAggs(reference.doc_aggs),
    }
  }

  if (typeof data.session_id === 'string' && data.session_id !== '') {
    next = { ...next, sessionId: data.session_id }
  }
  if (typeof data.id === 'string' && data.id !== '') {
    next = { ...next, messageId: data.id }
  }

  return next
}
