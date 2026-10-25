/**
 * Datasety (08 §7.3, §7.4; kontrakt WP E3-3a §T1): lista, szczegół, mutacje CRUD oraz
 * podsumowanie i logi ingestii. Wzór: `features/chats/queries.ts` — jawne `queryOptions`,
 * rozpakowanie listy przez `unwrapList('datasets', …)`, weryfikacja koperty przez `apiCall`.
 * Każda mutacja unieważnia `datasetKeys.all`: pod tym prefiksem siedzą też lista
 * `features/chats/datasetsQuery.ts` i sekcja Home — odświeżają się razem (zamierzone).
 * DEC-100: `Dataset` to wygenerowany schemat `DatasetDetail` (GET/PUT `/datasets/{id}` niosą `size`).
 */

import { queryOptions, useMutation, useQueryClient } from '@tanstack/react-query'
import type { QueryClient } from '@tanstack/react-query'

import { api, apiCall } from '../../api/client'
import { unwrapList } from '../../api/lists'
import type { components } from '../../api/schema.gen'

/** Szczegół datasetu: `DatasetDetail` = `Dataset` + `connectors` + `size` (kontrakt §Fakty API). */
export type Dataset = components['schemas']['DatasetDetail']
export type DatasetListed = components['schemas']['DatasetListed']
export type IngestionLog = components['schemas']['IngestionLog']
export type IngestionSummary = components['schemas']['IngestionSummary']
/** Odpowiedź POST `/datasets` (`RagflowOk_Dataset_`) — bez `connectors` i `size` (DEC-100 p. 3). */
export type CreatedDataset = components['schemas']['Dataset']

export const datasetKeys = {
  all: ['datasets'] as const,
  list: (params?: { keywords?: string }) => ['datasets', 'list', params ?? {}] as const,
  detail: (id: string) => ['datasets', 'detail', id] as const,
  summary: (id: string) => ['datasets', 'detail', id, 'summary'] as const,
  logs: (id: string, params?: { status?: number; page?: number; pageSize?: number }) =>
    ['datasets', 'detail', id, 'logs', params ?? {}] as const,
  log: (id: string, logId: string) => ['datasets', 'detail', id, 'log', logId] as const,
}

/** Górna granica strony — lista baz wiedzy potrzebuje całości, nie pierwszej strony. */
const PAGE_SIZE = 1000

export function datasetsListQueryOptions(params?: { keywords?: string }) {
  return queryOptions({
    queryKey: datasetKeys.list(params),
    queryFn: async () => {
      const { data, error, response } = await api.GET('/api/v1/datasets', {
        params: {
          query: {
            page_size: PAGE_SIZE,
            orderby: 'update_time',
            desc: true,
            keywords: params?.keywords,
          },
        },
      })
      return unwrapList<DatasetListed>('datasets', response.ok ? data : error, response.status)
        .items
    },
  })
}

export function datasetQueryOptions(id: string) {
  return queryOptions({
    queryKey: datasetKeys.detail(id),
    queryFn: () =>
      apiCall<Dataset>(
        api.GET('/api/v1/datasets/{dataset_id}', { params: { path: { dataset_id: id } } }),
      ),
  })
}

function invalidateDatasets(queryClient: QueryClient): void {
  void queryClient.invalidateQueries({ queryKey: datasetKeys.all })
}

/** Tworzenie datasetu: backend nadaje wartości domyślne, wysyłamy trzy pola wybrane w dialogu. */
export function useCreateDataset() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (input: { name: string; embeddingModel: string; chunkMethod: ChunkMethod }) =>
      apiCall<CreatedDataset>(
        api.POST('/api/v1/datasets', {
          // Wygenerowany typ wymaga wszystkich kluczy, choć backend przyjmuje tylko te trzy
          // (jak `CreateChatRequest` w `useCreateChat`). `embedding_model` to `model_id`
          // z `GET /api/v1/models` (kontrakt §T2).
          body: {
            name: input.name,
            embedding_model: input.embeddingModel,
            chunk_method: input.chunkMethod,
          } as unknown as components['schemas']['CreateDatasetRequest'],
        }),
      ),
    onSuccess: () => invalidateDatasets(queryClient),
  })
}

/** Zmiana datasetu: PUT wysyła wyłącznie zmienione pola (wołający buduje łatkę w T4). */
export function useUpdateDataset(id: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (patch: Record<string, unknown>) =>
      apiCall<Dataset>(
        api.PUT('/api/v1/datasets/{dataset_id}', {
          params: { path: { dataset_id: id } },
          body: patch as unknown as components['schemas']['UpdateDatasetRequest'],
        }),
      ),
    onSuccess: (updated) => {
      // T10 (QA-UI #3): odpowiedź PUT od razu do cache szczegółu — loader zakładki Konfiguracja
      // oddaje zapisane wartości nawet w oknie świeżości `staleTime`; przed podmianą kolejność:
      // `setQueryData` zeruje `isInvalidated`, więc unieważnienie idzie po nim.
      queryClient.setQueryData(datasetKeys.detail(id), updated)
      invalidateDatasets(queryClient)
    },
  })
}

/** Usuwanie masowe: ciało to `{ids}`, `delete_all` zostaje na domyślnej wartości backendu. */
export function useDeleteDatasets() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (ids: string[]) =>
      apiCall<components['schemas']['SuccessCount']>(
        api.DELETE('/api/v1/datasets', {
          body: { ids } as unknown as components['schemas']['DeleteDatasetsRequest'],
        }),
      ),
    onSuccess: () => invalidateDatasets(queryClient),
  })
}

export function ingestionSummaryQueryOptions(id: string) {
  return queryOptions({
    queryKey: datasetKeys.summary(id),
    queryFn: () =>
      apiCall<IngestionSummary>(
        api.GET('/api/v1/datasets/{dataset_id}/ingestions/summary', {
          params: { path: { dataset_id: id } },
        }),
      ),
  })
}

export function ingestionLogsQueryOptions(
  id: string,
  params: { status?: number; page?: number; pageSize?: number },
) {
  return queryOptions({
    queryKey: datasetKeys.logs(id, params),
    queryFn: () =>
      apiCall<components['schemas']['IngestionsList']>(
        api.GET('/api/v1/datasets/{dataset_id}/ingestions', {
          params: {
            path: { dataset_id: id },
            query: {
              page: params.page,
              page_size: params.pageSize,
              orderby: 'create_time',
              desc: true,
              // Domyślne `log_type=dataset` zwraca zawsze pustą listę (kontrakt §Fakty API).
              log_type: 'file',
              operation_status: params.status === undefined ? undefined : [String(params.status)],
            },
          },
        }),
      ),
  })
}

export function ingestionLogQueryOptions(id: string, logId: string) {
  return queryOptions({
    queryKey: datasetKeys.log(id, logId),
    queryFn: () =>
      apiCall<IngestionLog>(
        api.GET('/api/v1/datasets/{dataset_id}/ingestions/{log_id}', {
          params: { path: { dataset_id: id, log_id: logId } },
        }),
      ),
  })
}

export const CHUNK_METHODS = [
  'naive',
  'qa',
  'manual',
  'table',
  'paper',
  'book',
  'laws',
  'presentation',
  'one',
] as const

export type ChunkMethod = (typeof CHUNK_METHODS)[number]
