/**
 * Wyszukiwarki (kontrakt WP E4-4b §1): lista, szczegół oraz mutacje CRUD i zapis konfiguracji.
 * Wywołania przez `api`/`apiCall` (jak w `features/chats/queries.ts`); koperta `code ≠ 0` →
 * `ApiError`. Każda mutacja unieważnia `searchKeys.all`, więc lista i szczegóły odświeżają się
 * po zapisie.
 */

import { queryOptions, useMutation, useQueryClient } from '@tanstack/react-query'
import type { QueryClient } from '@tanstack/react-query'

import { api, apiCall } from '../../api/client'
import type { components } from '../../api/schema.gen'

import { buildUpdateBody } from './settings/schema'
import type { SearchSettingsValues } from './settings/schema'

export type SearchApp = components['schemas']['SearchApp']
export type SearchListItem = components['schemas']['SearchListItem']
export type SearchConfig = components['schemas']['SearchConfig']
export type RawSearchConfig = Record<string, unknown>

export const searchKeys = {
  all: ['searches'] as const,
  list: () => ['searches', 'list'] as const,
  detail: (id: string) => ['searches', 'detail', id] as const,
}

/** Lista wyszukiwarek: `data` koperty to `{search_apps, total}`, rozpakowujemy same wiersze. */
export function searchesListQueryOptions() {
  return queryOptions({
    queryKey: searchKeys.list(),
    queryFn: () =>
      apiCall<components['schemas']['SearchList']>(api.GET('/api/v1/searches')).then(
        (data) => data.search_apps,
      ),
  })
}

export function searchQueryOptions(id: string) {
  return queryOptions({
    queryKey: searchKeys.detail(id),
    queryFn: () =>
      apiCall<SearchApp>(
        api.GET('/api/v1/searches/{search_id}', { params: { path: { search_id: id } } }),
      ),
  })
}

function invalidateSearches(queryClient: QueryClient): void {
  void queryClient.invalidateQueries({ queryKey: searchKeys.all })
}

/** Tworzenie wyszukiwarki: backend nadaje wartości domyślne, ciało to tylko `{name}`. */
export function useCreateSearch() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (name: string) =>
      apiCall<components['schemas']['SearchCreateResult']>(
        api.POST('/api/v1/searches', {
          // Wygenerowany typ wymaga pełnego ciała, a backend przyjmuje samo `{name}`
          // (jak `useCreateChat`).
          body: { name } as unknown as components['schemas']['SearchCreateRequest'],
        }),
      ),
    onSuccess: () => invalidateSearches(queryClient),
  })
}

/**
 * Zmiana nazwy: PUT wymaga pełnego ciała — backend odrzuca żądanie bez `search_config`
 * kodem 101 (K15/złoto `searches--15`), więc dokładamy `description` i `search_config`
 * z bieżącego obiektu (`ensureQueryData` pobiera go, gdy nie ma go w pamięci).
 */
export function useRenameSearch() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({ id, name }: { id: string; name: string }) => {
      const app = await queryClient.ensureQueryData(searchQueryOptions(id))
      return apiCall<components['schemas']['SearchUpdateResult']>(
        api.PUT('/api/v1/searches/{search_id}', {
          params: { path: { search_id: id } },
          body: {
            name,
            description: app.description ?? '',
            search_config: app.search_config,
          } as unknown as components['schemas']['SearchUpdateRequest'],
        }),
      )
    },
    onSuccess: () => invalidateSearches(queryClient),
  })
}

/** Usunięcie wyszukiwarki: `data` koperty to `true`/`false`. */
export function useDeleteSearch() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: string) =>
      apiCall<boolean>(
        api.DELETE('/api/v1/searches/{search_id}', { params: { path: { search_id: id } } }),
      ),
    onSuccess: () => invalidateSearches(queryClient),
  })
}

/**
 * Zapis ustawień: PUT z pełnym `search_config` scalonym z bieżącym obiektem (`buildUpdateBody`),
 * dzięki czemu klucze nieobsługiwane przez UI nie giną. Bieżący obiekt bierzemy z cache
 * szczegółu (`ensureQueryData` — pobiera go, gdy nie ma go jeszcze w pamięci).
 */
export function useUpdateSearchConfig(id: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (values: SearchSettingsValues) => {
      const current = await queryClient.ensureQueryData(searchQueryOptions(id))
      return apiCall<components['schemas']['SearchUpdateResult']>(
        api.PUT('/api/v1/searches/{search_id}', {
          params: { path: { search_id: id } },
          body: buildUpdateBody(
            values,
            current,
          ) as unknown as components['schemas']['SearchUpdateRequest'],
        }),
      )
    },
    onSuccess: () => invalidateSearches(queryClient),
  })
}
