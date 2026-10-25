import { HttpResponse, http } from 'msw'
import type { HttpHandler } from 'msw'

import type { Chunk, ChunkDoc } from '../../../features/datasets/chunks/queries'
import { CHUNKS_PAGE_SIZE } from '../../../features/datasets/chunks/queries'
import { apiUrl } from './common'
import { fixtureDocument } from './documents'

/** Pełny chunk (12 kluczy, kontrakt WP E3-4a §Fakty API). */
export function fixtureChunk(overrides: Partial<Chunk> = {}): Chunk {
  return {
    id: 'chunk-1',
    content: 'Treść chunku',
    available: true,
    doc_type_kwd: 'text',
    docnm_kwd: '',
    document_id: 'doc-1',
    dataset_id: 'ds-1',
    image_id: '',
    important_keywords: [],
    questions: [],
    tag_kwd: [],
    positions: [],
    ...overrides,
  }
}

/** Żądanie widziane przez `opts.onRequest` (metoda, pełny adres i ciało; lista przekazuje `null`). */
export type ChunksRequest = { method: string; url: string; body: unknown }

/**
 * Handlery chunków z pamięcią stanu (wzór `documentsHandlers`): lista z paginacją i filtrem
 * treści, tworzenie, przełączenie `available`, aktualizacja i usuwanie (kontrakt WP E3-4a).
 * Każde wywołanie daje świeży magazyn, a `server.resetHandlers()` wraca między testami do stanu
 * z `handlers`. Odpowiedzi niosą dokument (`doc`) zbudowany z `fixtureDocument` — typ
 * `DocumentListed` nie ma `content_hash`, więc dokładamy to pole (bez rzutowania).
 */
export function chunksHandlers(
  initial: Chunk[] = [],
  opts: { onRequest?: (req: ChunksRequest) => void } = {},
): HttpHandler[] {
  const store = new Map(initial.map((chunk) => [chunk.id, { ...chunk }]))
  let nextId = store.size + 1

  const doc = (): ChunkDoc => ({
    ...fixtureDocument({ id: 'doc-1', name: 'plik.pdf', chunk_count: store.size }),
    content_hash: '',
  })

  const base = '/api/v1/datasets/:datasetId/documents/:documentId/chunks'

  return [
    http.get(apiUrl(base), ({ request }) => {
      const url = new URL(request.url)
      opts.onRequest?.({ method: 'GET', url: request.url, body: null })
      const keywords = url.searchParams.get('keywords')?.toLowerCase() ?? ''
      const available = url.searchParams.get('available')
      const matched = [...store.values()].filter((chunk) => {
        if (keywords !== '' && !chunk.content.toLowerCase().includes(keywords)) return false
        // Jak backend (kontrakt §K3): `'true'` → tylko włączone; inna obecna wartość → tylko
        // wyłączone; brak parametru → wszystkie.
        if (available === null) return true
        return available === 'true' ? chunk.available : !chunk.available
      })
      const page = Number(url.searchParams.get('page') ?? '1')
      const pageSize = Number(url.searchParams.get('page_size') ?? String(CHUNKS_PAGE_SIZE))
      const from = (page - 1) * pageSize
      return HttpResponse.json({
        code: 0,
        message: 'success',
        data: { chunks: matched.slice(from, from + pageSize), doc: doc(), total: matched.length },
      })
    }),

    http.post(apiUrl(base), async ({ request }) => {
      const body = (await request.json()) as {
        content?: string
        important_keywords?: string[]
        questions?: string[]
      }
      opts.onRequest?.({ method: 'POST', url: request.url, body })
      const id = `new-${nextId}`
      nextId += 1
      store.set(
        id,
        fixtureChunk({
          id,
          content: body.content ?? '',
          important_keywords: body.important_keywords ?? [],
          questions: body.questions ?? [],
        }),
      )
      return HttpResponse.json({ code: 0, message: 'success', data: { chunk: { id } } })
    }),

    // Przełączenie `available` dla wielu chunków (trasa statyczna) PRZED trasą z `:chunkId`.
    http.patch(apiUrl(base), async ({ request }) => {
      const body = (await request.json()) as { chunk_ids?: string[]; available?: boolean }
      opts.onRequest?.({ method: 'PATCH', url: request.url, body })
      for (const id of body.chunk_ids ?? []) {
        const current = store.get(id)
        if (current !== undefined) {
          store.set(id, { ...current, available: body.available ?? current.available })
        }
      }
      return HttpResponse.json({ code: 0, message: 'success', data: true })
    }),

    http.patch(apiUrl(`${base}/:chunkId`), async ({ request, params }) => {
      const body = (await request.json()) as {
        content?: string | null
        important_keywords?: string[] | null
        questions?: string[] | null
        available?: number | null
      }
      opts.onRequest?.({ method: 'PATCH', url: request.url, body })
      const current = store.get(String(params.chunkId))
      if (current === undefined) {
        return HttpResponse.json({ code: 102, message: 'Chunk not found', data: null })
      }
      const updated: Chunk = {
        ...current,
        ...(body.content != null ? { content: body.content } : {}),
        ...(body.important_keywords != null ? { important_keywords: body.important_keywords } : {}),
        ...(body.questions != null ? { questions: body.questions } : {}),
        // W pojedynczym PATCH `available` przychodzi jako liczba 0/1 (kontrakt §Wskazówki).
        ...(body.available != null ? { available: body.available === 1 } : {}),
      }
      store.set(updated.id, updated)
      return HttpResponse.json({ code: 0, message: 'success', data: null })
    }),

    http.delete(apiUrl(base), async ({ request }) => {
      const body = (await request.json()) as { chunk_ids?: string[] }
      opts.onRequest?.({ method: 'DELETE', url: request.url, body })
      for (const id of body.chunk_ids ?? []) store.delete(id)
      return HttpResponse.json({ code: 0, message: 'success', data: null })
    }),
  ]
}
