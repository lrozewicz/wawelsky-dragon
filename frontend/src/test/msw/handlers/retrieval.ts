import { HttpResponse, http } from 'msw'
import type { HttpHandler } from 'msw'

import type { DocAgg, RetrievalChunk } from '../../../features/datasets/retrieval/queries'

import { apiUrl } from './common'

// Odpowiednik elementu `data.chunks` z backend/openapi.json (operacja `retrieval_query`) —
// pola jak w złocie backend/tests/contract/golden/.../retrieval--06.json.
export function fixtureRetrievalChunk(overrides: Partial<RetrievalChunk> = {}): RetrievalChunk {
  return {
    id: 'chunk-1',
    content: 'Treść fragmentu',
    content_ltks: '',
    dataset_id: 'ds-1',
    doc_type_kwd: '',
    document_id: 'doc-1',
    document_keyword: 'plik.pdf',
    image_id: '',
    important_keywords: [],
    mom_id: '',
    positions: [],
    row_id: null,
    similarity: 0.85,
    tag_kwd: [],
    term_similarity: 0.7,
    vector_similarity: 0.9,
    highlight: null,
    ...overrides,
  }
}

/**
 * Handlery testu retrievalu (`POST /api/v1/retrieval`, kontrakt WP E3-H2a §K4): zwraca podane
 * fragmenty przefiltrowane po `document_ids` (gdy podane) i po `similarity >= similarity_threshold`,
 * z `doc_aggs` zliczonymi po `document_id` i `total` liczonym PRZED ucięciem do `page_size`.
 * Odrzuca kodem 102 (HTTP 409) `knn_top_k: null` i `cross_languages` niebędące listą (DEC-155).
 * Domyślnie (bez `options`) — pusta lista. Nie wchodzi do `handlers` domyślnych: testy wołają
 * `server.use(...retrievalHandlers(...))`.
 */
export function retrievalHandlers(
  options: { chunks?: RetrievalChunk[]; onRequest?: (body: Record<string, unknown>) => void } = {},
): HttpHandler[] {
  return [
    http.post(apiUrl('/api/v1/retrieval'), async ({ request }) => {
      const body = (await request.json()) as Record<string, unknown>
      options.onRequest?.(body)

      // K4/DEC-155: jak backend — `knn_top_k: null` → int(None) → 102; nie-lista języków → 102
      // (`Conflict` backendu ma HTTP 409). Pozostałe walidacje backendu tu pomijamy.
      if (body.knn_top_k === null) {
        return HttpResponse.json(
          { code: 102, message: '`knn_top_k` should be a number', data: null },
          { status: 409 },
        )
      }
      const crossLanguages = body.cross_languages
      if (
        crossLanguages !== undefined &&
        crossLanguages !== null &&
        !Array.isArray(crossLanguages)
      ) {
        return HttpResponse.json(
          { code: 102, message: '`cross_languages` should be a list', data: null },
          { status: 409 },
        )
      }

      const threshold =
        typeof body.similarity_threshold === 'number' ? body.similarity_threshold : 0
      // Kontrakt WP E4-H1 §T4: `document_ids` to nazwa z API, a UI wyszukiwarek wysyła `doc_ids`
      // (`useSearchHits`) — handler przyjmuje oba, preferując nazwę kontraktową.
      const ids = Array.isArray(body.document_ids) ? body.document_ids : body.doc_ids
      const documentIds = Array.isArray(ids) ? (ids as string[]) : null
      const pageSize = typeof body.page_size === 'number' ? body.page_size : null

      const matched = (options.chunks ?? []).filter(
        (chunk) =>
          chunk.similarity >= threshold &&
          (documentIds === null || documentIds.includes(chunk.document_id)),
      )

      const aggs = new Map<string, DocAgg>()
      for (const chunk of matched) {
        const agg = aggs.get(chunk.document_id) ?? {
          doc_id: chunk.document_id,
          doc_name: chunk.document_keyword,
          count: 0,
        }
        aggs.set(chunk.document_id, { ...agg, count: agg.count + 1 })
      }

      return HttpResponse.json({
        code: 0,
        message: 'success',
        data: {
          chunks: pageSize === null ? matched : matched.slice(0, pageSize),
          doc_aggs: [...aggs.values()],
          total: matched.length,
        },
      })
    }),
  ]
}
