/**
 * Mutacje chunków (08 §7.5, kontrakt WP E3-4a §Pliki i sygnatury). Wzór:
 * `features/datasets/files/mutations.ts` — `useMutation` + `apiCall`, trasy v0.27
 * (`chunks_create`, `chunks_update`, `chunks_switch`, `chunks_delete`). Po każdej operacji
 * unieważniamy stronę chunków oraz liczniki nagłówka (`documentKeys.all`, `datasetKeys.detail`),
 * bo zmienia się `chunk_count` dokumentu. `useSwitchChunks` przełącza `available` optymistycznie:
 * podmienia pole w cache przed odpowiedzią, a przy błędzie przywraca snapshot z `onMutate`.
 */

import { useMutation, useQueryClient } from '@tanstack/react-query'
import type { QueryClient } from '@tanstack/react-query'

import { api, apiCall } from '../../../api/client'
import type { components } from '../../../api/schema.gen'
import { datasetKeys } from '../queries'
import { documentKeys } from '../files/queries'
import { chunkKeys } from './queries'
import type { ChunksData } from './queries'

/** Pola formularza chunku (kontrakt §Pliki i sygnatury). */
export type ChunkInput = { content: string; important_keywords: string[]; questions: string[] }

/** Łatka PATCH pojedynczego chunku — tylko zmieniane pola (`available` to liczba 0/1). */
export type ChunkPatch = Partial<ChunkInput> & { available?: 0 | 1 }

/** Unieważnia stronę chunków, listę dokumentów datasetu i licznik w nagłówku szczegółów. */
function invalidateChunks(queryClient: QueryClient, datasetId: string, docId: string): void {
  void queryClient.invalidateQueries({ queryKey: chunkKeys.all(datasetId, docId) })
  void queryClient.invalidateQueries({ queryKey: documentKeys.all(datasetId) })
  void queryClient.invalidateQueries({ queryKey: datasetKeys.detail(datasetId) })
}

export function useCreateChunk(datasetId: string, docId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (input: ChunkInput) =>
      apiCall<components['schemas']['ChunkCreated']>(
        api.POST('/api/v1/datasets/{dataset_id}/documents/{document_id}/chunks', {
          params: { path: { dataset_id: datasetId, document_id: docId } },
          body: input,
        }),
      ),
    onSettled: () => invalidateChunks(queryClient, datasetId, docId),
  })
}

export function useUpdateChunk(datasetId: string, docId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (input: { id: string; patch: ChunkPatch }) =>
      apiCall<void>(
        api.PATCH('/api/v1/datasets/{dataset_id}/documents/{document_id}/chunks/{chunk_id}', {
          params: {
            path: { dataset_id: datasetId, document_id: docId, chunk_id: input.id },
          },
          body: input.patch,
        }),
      ),
    onSettled: () => invalidateChunks(queryClient, datasetId, docId),
  })
}

export function useSwitchChunks(datasetId: string, docId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (input: { ids: string[]; available: boolean }) =>
      apiCall<boolean>(
        api.PATCH('/api/v1/datasets/{dataset_id}/documents/{document_id}/chunks', {
          params: { path: { dataset_id: datasetId, document_id: docId } },
          body: {
            chunk_ids: input.ids,
            available: input.available,
          },
        }),
      ),
    onMutate: async (input) => {
      await queryClient.cancelQueries({ queryKey: chunkKeys.all(datasetId, docId) })
      const snapshot = queryClient.getQueriesData<ChunksData>({
        queryKey: chunkKeys.all(datasetId, docId),
      })
      queryClient.setQueriesData<ChunksData>(
        { queryKey: chunkKeys.all(datasetId, docId) },
        (previous) => {
          if (previous === undefined) return previous
          return {
            ...previous,
            chunks: previous.chunks.map((chunk) =>
              input.ids.includes(chunk.id) ? { ...chunk, available: input.available } : chunk,
            ),
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
    onSettled: () => invalidateChunks(queryClient, datasetId, docId),
  })
}

export function useDeleteChunks(datasetId: string, docId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (input: { ids: string[] }) =>
      apiCall<void>(
        api.DELETE('/api/v1/datasets/{dataset_id}/documents/{document_id}/chunks', {
          params: { path: { dataset_id: datasetId, document_id: docId } },
          // `delete_all` zostaje na domyślnej wartości backendu (wzór `useDeleteDocuments`).
          body: {
            chunk_ids: input.ids,
          } as unknown as components['schemas']['DeleteChunksRequest'],
        }),
      ),
    onSettled: () => invalidateChunks(queryClient, datasetId, docId),
  })
}
