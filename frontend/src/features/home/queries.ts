/**
 * Zapytania strony Home (08 §7.2): 4 ostatnio zmienione bazy wiedzy i 4 ostatnie czaty.
 * Listy mają różne kształty per endpoint, dlatego rozpakowujemy je przez `unwrapList`.
 */

import { queryOptions, useQuery } from '@tanstack/react-query'

import { api } from '../../api/client'
import { unwrapList } from '../../api/lists'
import type { components } from '../../api/schema.gen'

export type DatasetListItem = components['schemas']['DatasetListed']
export type ChatListItem = components['schemas']['ChatListItem']

/** Liczba kart w rzędzie „ostatnie” na stronie Home (08 §7.2). */
export const RECENT_LIMIT = 4

type ApiResult = { data?: unknown; error?: unknown; response: Response }

/** Wspólne rozpakowanie listy — sukces w `data`, błąd transportu w `error` (jak `unwrap`). */
function unwrapItems<T>(endpoint: 'datasets' | 'chats', result: ApiResult): T[] {
  const { data, error, response } = result
  return unwrapList<T>(endpoint, response.ok ? data : error, response.status).items
}

export function recentDatasetsQueryOptions() {
  return queryOptions({
    queryKey: ['datasets', 'recent'],
    queryFn: async () =>
      unwrapItems<DatasetListItem>(
        'datasets',
        await api.GET('/api/v1/datasets', {
          params: { query: { page_size: RECENT_LIMIT, orderby: 'update_time' } },
        }),
      ),
  })
}

export function recentChatsQueryOptions() {
  return queryOptions({
    queryKey: ['chats', 'recent'],
    queryFn: async () =>
      unwrapItems<ChatListItem>(
        'chats',
        await api.GET('/api/v1/chats', { params: { query: { page_size: RECENT_LIMIT } } }),
      ),
  })
}

export function useRecentDatasets() {
  return useQuery(recentDatasetsQueryOptions())
}

export function useRecentChats() {
  return useQuery(recentChatsQueryOptions())
}
