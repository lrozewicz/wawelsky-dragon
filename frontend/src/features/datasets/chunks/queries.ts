/**
 * Warstwa danych strony chunków (08 §7.5, kontrakt WP E3-H2a §K3). Wzór:
 * `features/datasets/files/queries.ts` — jawne `queryOptions`, rozpakowanie listy przez
 * `unwrapList('chunks', …)` (zwraca `chunks`, `total` i `doc` = `DocumentFull`), klucz pod
 * prefiksem `['datasets']` (`datasetKeys.detail` unieważnia też chunki). Paginacja serwerowa;
 * puste `keywords` i filtr `all` nie trafiają do zapytania (filtr pełnotekstowy i dostępności
 * robi serwer).
 */

import { keepPreviousData, queryOptions } from '@tanstack/react-query'

import { api } from '../../../api/client'
import { unwrapList } from '../../../api/lists'
import type { components } from '../../../api/schema.gen'

/** Element listy chunków (12 kluczy, kontrakt §Fakty API). */
export type Chunk = components['schemas']['Chunk']
/** Dokument towarzyszący liście chunków — pełny kształt (`DocumentFull`). */
export type ChunkDoc = components['schemas']['DocumentFull']

/** Filtr dostępności listy chunków — mapowany na parametr `available` (kontrakt §K3). */
export type ChunksFilter = 'all' | 'enabled' | 'disabled'

/** Parametry listy chunków: strona (od 1), rozmiar strony, filtr treści i filtr dostępności. */
export type ChunksQuery = {
  page: number
  pageSize: number
  keywords: string
  available: ChunksFilter
}

/** Odpowiedź listy: strona chunków, liczba łączna i dokument (kontrakt §Fakty API). */
export type ChunksData = { chunks: Chunk[]; total: number; doc: ChunkDoc }

/** Rozmiar strony chunków (kontrakt §Fakty API). */
export const CHUNKS_PAGE_SIZE = 30

export const chunkKeys = {
  all: (datasetId: string, docId: string) =>
    ['datasets', 'detail', datasetId, 'chunks', docId] as const,
  list: (datasetId: string, docId: string, q: ChunksQuery) =>
    ['datasets', 'detail', datasetId, 'chunks', docId, q] as const,
}

export function chunksListQueryOptions(datasetId: string, docId: string, q: ChunksQuery) {
  return queryOptions({
    queryKey: chunkKeys.list(datasetId, docId, q),
    queryFn: async () => {
      const { data, error, response } = await api.GET(
        '/api/v1/datasets/{dataset_id}/documents/{document_id}/chunks',
        {
          params: {
            path: { dataset_id: datasetId, document_id: docId },
            query: {
              page: q.page,
              page_size: q.pageSize,
              // Pusty `keywords` nie trafia do adresu (wyszukiwanie serwerowe).
              keywords: q.keywords === '' ? undefined : q.keywords,
              // `all` pomija parametr; `enabled`/`disabled` jadą jako `'true'`/`'false'` (kontrakt §K3).
              available:
                q.available === 'all' ? undefined : q.available === 'enabled' ? 'true' : 'false',
            },
          },
        },
      )
      const { items, total, doc } = unwrapList<Chunk>(
        'chunks',
        response.ok ? data : error,
        response.status,
      )
      return { chunks: items, total, doc: doc as ChunkDoc }
    },
    // Paginacja bez migotania: poprzednia strona zostaje w cache, gdy leci nowa.
    placeholderData: keepPreviousData,
  })
}
