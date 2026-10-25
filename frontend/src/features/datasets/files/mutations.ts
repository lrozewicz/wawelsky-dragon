/**
 * Mutacje dokumentów datasetu (kontrakt WP E3-3b §T1b). Wzór: `features/datasets/queries.ts` —
 * `useMutation` + `apiCall`, trasy v0.27 (`documents_update`, `documents_delete`, `documents_parse`,
 * `documents_stop`, `documents_batch_update_status`). Po zmianie unieważniamy listę dokumentów
 * tego datasetu (`documentKeys.all`) i liczniki nagłówka (`datasetKeys.detail`); parse i stop
 * zmieniają wyłącznie stan listy, więc odświeżają tylko ją.
 * `useToggleDocument` przełącza „Włączony” optymistycznie: podmienia `status` w cache, zanim
 * przyjdzie odpowiedź, a przy błędzie przywraca snapshot zapisany w `onMutate`.
 */

import { useMutation, useQueryClient } from '@tanstack/react-query'
import type { QueryClient } from '@tanstack/react-query'

import { api, apiCall } from '../../../api/client'
import type { components } from '../../../api/schema.gen'
import { datasetKeys } from '../queries'
import { runpodPreflight } from '../../runpod/api'
import { hasRunpodPromptHost, openRunpodPrompt } from '../../runpod/promptStore'
import { documentKeys } from './queries'
import type { DocumentRow } from './queries'

/** Kształt danych listy dokumentów w cache (patrz `documentsListQueryOptions`). */
type DocumentsListData = { docs: DocumentRow[]; total: number }

/** Łatka PATCH: wysyłamy wyłącznie zmieniane pola (`enabled` to liczba 0/1). */
export type DocumentPatch = {
  name?: string
  enabled?: 0 | 1
  chunk_method?: string
  /** Kontrakt WP E5-H8c §3: pełny, scalony obiekt konfiguracji z dialogu metody pliku. */
  parser_config?: Record<string, unknown>
}

/** Unieważnia listę dokumentów datasetu oraz licznik w nagłówku szczegółów. */
function invalidateDocuments(queryClient: QueryClient, datasetId: string): void {
  void queryClient.invalidateQueries({ queryKey: documentKeys.all(datasetId) })
  void queryClient.invalidateQueries({ queryKey: datasetKeys.detail(datasetId) })
}

export function useUpdateDocument(datasetId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (input: { id: string; patch: DocumentPatch }) =>
      apiCall<DocumentRow>(
        api.PATCH('/api/v1/datasets/{dataset_id}/documents/{document_id}', {
          params: { path: { dataset_id: datasetId, document_id: input.id } },
          body: input.patch,
        }),
      ),
    onSettled: () => invalidateDocuments(queryClient, datasetId),
  })
}

export function useToggleDocument(datasetId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (input: { id: string; enabled: boolean }) =>
      apiCall<DocumentRow>(
        api.PATCH('/api/v1/datasets/{dataset_id}/documents/{document_id}', {
          params: { path: { dataset_id: datasetId, document_id: input.id } },
          body: {
            enabled: input.enabled ? 1 : 0,
          },
        }),
      ),
    onMutate: async (input) => {
      await queryClient.cancelQueries({ queryKey: documentKeys.all(datasetId) })
      const snapshot = queryClient.getQueriesData<DocumentsListData>({
        queryKey: documentKeys.all(datasetId),
      })
      const status: DocumentRow['status'] = input.enabled ? '1' : '0'
      queryClient.setQueriesData<DocumentsListData>(
        { queryKey: documentKeys.all(datasetId) },
        (previous) => {
          if (previous === undefined) return previous
          return {
            ...previous,
            docs: previous.docs.map((doc) => (doc.id === input.id ? { ...doc, status } : doc)),
          }
        },
      )
      return { snapshot }
    },
    onError: (_error, _input, context) => {
      for (const [key, data] of context?.snapshot ?? []) {
        queryClient.setQueryData(key, data)
      }
    },
    onSettled: () => invalidateDocuments(queryClient, datasetId),
  })
}

export function useDeleteDocuments(datasetId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (input: { ids: string[] }) =>
      apiCall<components['schemas']['DeletedCount']>(
        api.DELETE('/api/v1/datasets/{dataset_id}/documents', {
          params: { path: { dataset_id: datasetId } },
          // `delete_all` zostaje na domyślnej wartości backendu (wzór `useDeleteDatasets`).
          body: {
            ids: input.ids,
          } as unknown as components['schemas']['DeleteDocumentsRequest'],
        }),
      ),
    onSettled: () => invalidateDocuments(queryClient, datasetId),
  })
}

export function useParseDocuments(datasetId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (input: { ids: string[] }) => {
      // Parser działający na RunPod, a pod wyłączony: zamiast parsować (i kończyć błędem) pytamy
      // „włączyć pod?”. Po wdrożeniu WD samo uruchomi parsowanie tych dokumentów.
      if (hasRunpodPromptHost()) {
        const preflight = await runpodPreflight(datasetId, input.ids)
        if (preflight?.needs_pod) {
          openRunpodPrompt({ datasetId, documentIds: input.ids, preflight })
          return { success_count: 0 } as components['schemas']['SuccessCount']
        }
      }
      return apiCall<components['schemas']['SuccessCount']>(
        api.POST('/api/v1/datasets/{dataset_id}/documents/parse', {
          params: { path: { dataset_id: datasetId } },
          body: { document_ids: input.ids },
        }),
      )
    },
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: documentKeys.all(datasetId) })
    },
  })
}

export function useStopDocuments(datasetId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (input: { ids: string[] }) =>
      apiCall<components['schemas']['StopResult']>(
        api.POST('/api/v1/datasets/{dataset_id}/documents/stop', {
          params: { path: { dataset_id: datasetId } },
          body: { document_ids: input.ids },
        }),
      ),
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: documentKeys.all(datasetId) })
    },
  })
}

export function useBatchUpdateStatus(datasetId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (input: { ids: string[]; enabled: boolean }) =>
      apiCall<Record<string, components['schemas']['DocumentStatus']>>(
        api.POST('/api/v1/datasets/{dataset_id}/documents/batch-update-status', {
          params: { path: { dataset_id: datasetId } },
          body: { doc_ids: input.ids, status: input.enabled ? '1' : '0' },
        }),
      ),
    onSettled: () => invalidateDocuments(queryClient, datasetId),
  })
}
