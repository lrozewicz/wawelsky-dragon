/**
 * Lista baz wiedzy dla multi-selectu w ustawieniach czatu (08 §8.2) — wzór z
 * `features/home/queries.ts`: jawne `queryOptions`, rozpakowanie przez `unwrapList('datasets', …)`.
 */

import { queryOptions } from '@tanstack/react-query'

import { api } from '../../api/client'
import { unwrapList } from '../../api/lists'
import type { components } from '../../api/schema.gen'

export type DatasetListItem = components['schemas']['DatasetListed']

/** Górna granica strony — szuflada potrzebuje całej listy baz, a nie pierwszej strony. */
const PAGE_SIZE = 1000

export function datasetsListQueryOptions() {
  return queryOptions({
    queryKey: ['datasets', 'list'] as const,
    queryFn: async () => {
      const { data, error, response } = await api.GET('/api/v1/datasets', {
        params: { query: { page_size: PAGE_SIZE } },
      })
      return unwrapList<DatasetListItem>('datasets', response.ok ? data : error, response.status)
        .items
    },
  })
}
