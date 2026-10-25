/**
 * Warstwa danych plików datasetu (kontrakt WP E3-3b §T1a). Wzór: `features/datasets/queries.ts` —
 * jawne `queryOptions`, rozpakowanie listy przez `unwrapList('documents', …)`, klucz pod prefiksem
 * `['datasets']` (`datasetKeys.all` unieważnia też pliki). Lista odświeża się cyklicznie, dopóki
 * któryś dokument się parsuje (`shouldPoll`).
 */

import { keepPreviousData, queryOptions } from '@tanstack/react-query'

import { api } from '../../../api/client'
import { unwrapList } from '../../../api/lists'
import type { components } from '../../../api/schema.gen'
import { shouldPoll } from './polling'

export type DocumentRow = components['schemas']['DocumentListed']

/** Parametry listy plików: strona (od 1), sortowanie i filtry (puste = brak filtra). */
export type DocumentsQuery = {
  page: number
  pageSize: number
  orderby: 'create_time' | 'update_time' | 'name'
  desc: boolean
  keywords: string
  suffix: string[]
  run: string[]
  /** Filtr metadanych jako JSON `?metadata_condition=` (kontrakt WP E6-1b §2; `''` = brak). */
  metadataCondition: string
}

export const DEFAULT_DOCUMENTS_QUERY: DocumentsQuery = {
  page: 1,
  pageSize: 10,
  orderby: 'create_time',
  desc: true,
  keywords: '',
  suffix: [],
  run: [],
  metadataCondition: '',
}

export const documentKeys = {
  all: (datasetId: string) => ['datasets', 'detail', datasetId, 'documents'] as const,
  list: (datasetId: string, q: DocumentsQuery) =>
    ['datasets', 'detail', datasetId, 'documents', q] as const,
}

/** Odstęp odpytywania listy w trakcie parsowania (kontrakt §T1a). */
export const POLL_INTERVAL_MS = 3000

/** `''` i puste tablice nie trafiają do zapytania (openapi-fetch i tak pomija puste tablice). */
const blankToUndefined = (value: string): string | undefined => (value === '' ? undefined : value)

export function documentsListQueryOptions(datasetId: string, q: DocumentsQuery) {
  return queryOptions({
    queryKey: documentKeys.list(datasetId, q),
    queryFn: async () => {
      const { data, error, response } = await api.GET('/api/v1/datasets/{dataset_id}/documents', {
        params: {
          path: { dataset_id: datasetId },
          query: {
            page: q.page,
            page_size: q.pageSize,
            orderby: q.orderby,
            desc: q.desc,
            keywords: blankToUndefined(q.keywords),
            suffix: q.suffix.length === 0 ? undefined : q.suffix,
            run: q.run.length === 0 ? undefined : q.run,
            // Puste `metadata_condition` pomijamy (`blankToUndefined`); parametr zadeklarowany
            // w OpenAPI `documents_list` (T6 E7-H1), więc rzutowanie `as never` już niepotrzebne.
            metadata_condition: blankToUndefined(q.metadataCondition),
          },
        },
      })
      const { items, total } = unwrapList<DocumentRow>(
        'documents',
        response.ok ? data : error,
        response.status,
      )
      return { docs: items, total }
    },
    // Paginacja bez migotania: poprzednia strona zostaje w cache, gdy leci nowa.
    placeholderData: keepPreviousData,
    refetchInterval: (query) =>
      query.state.data && shouldPoll(query.state.data.docs) ? POLL_INTERVAL_MS : false,
  })
}
