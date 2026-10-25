/**
 * Mutacje UI Plików (kontrakt WP E4-5c §2). Wzór: `features/datasets/files/mutations.ts` —
 * `useMutation` + `apiCall`, a po zmianie unieważniamy cały prefiks `fileKeys.all`
 * (`useLinkFiles` dodatkowo `datasetKeys.all`, bo wiązania zmieniają też liczniki datasetów).
 * `useDeleteFiles` czyta kopertę ręcznie, bo kod 102 to częściowy sukces, a nie wyjątek.
 */

import { useMutation, useQueryClient } from '@tanstack/react-query'
import type { QueryClient } from '@tanstack/react-query'

import { api, apiCall } from '../../api/client'
import { ApiError } from '../../api/envelope'
import type { components } from '../../api/schema.gen'
import { datasetKeys } from '../datasets/queries'
import { fileKeys } from './queries'

/** Wynik usuwania: ile się udało i które elementy zawiodły (koperta 102). */
export type DeleteOutcome = { successCount: number; errors: string[] }

/** Unieważnia całą gałąź plików — listy, przodków i drzewo folderów. */
function invalidateFiles(queryClient: QueryClient): void {
  void queryClient.invalidateQueries({ queryKey: fileKeys.all })
}

export function useCreateFolder() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (input: { name: string; parentId: string | undefined }) =>
      apiCall<components['schemas']['FileCreated']>(
        api.POST('/api/v1/files', {
          // `files_create` deklaruje wariant JSON folderu (`FolderCreateBody`, C3).
          body: {
            name: input.name,
            type: 'folder',
            ...(input.parentId === undefined ? {} : { parent_id: input.parentId }),
          },
        }),
      ),
    onSettled: () => invalidateFiles(queryClient),
  })
}

export function useMoveFiles() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (input: { srcIds: string[]; destId: string }) =>
      apiCall<boolean>(
        api.POST('/api/v1/files/move', {
          body: { src_file_ids: input.srcIds, dest_file_id: input.destId },
        }),
      ),
    onSettled: () => invalidateFiles(queryClient),
  })
}

export function useRenameFile() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (input: { id: string; newName: string }) =>
      apiCall<boolean>(
        api.POST('/api/v1/files/move', {
          body: { src_file_ids: [input.id], new_name: input.newName },
        }),
      ),
    onSettled: () => invalidateFiles(queryClient),
  })
}

export function useLinkFiles() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (input: { fileIds: string[]; kbIds: string[]; mode?: 'replace' | 'add' }) =>
      apiCall<boolean>(
        api.POST('/api/v1/files/link-to-datasets', {
          // `mode` pomijamy, gdy nie podano (openapi-fetch nie wysyła `undefined`).
          params: { query: { mode: input.mode } },
          body: { file_ids: input.fileIds, kb_ids: input.kbIds },
        }),
      ),
    onSettled: () => {
      invalidateFiles(queryClient)
      void queryClient.invalidateQueries({ queryKey: datasetKeys.all })
    },
  })
}

export function useDeleteFiles() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (input: { ids: string[] }): Promise<DeleteOutcome> => {
      // Kontrakt §2: NIE `apiCall` — kod 102 to częściowy sukces, a nie wyjątek.
      const { data, error, response } = await api.DELETE('/api/v1/files', {
        body: { ids: input.ids },
      })
      const envelope = (data ?? error) as {
        code: number
        message?: string
        data?: { success_count: number; errors: string[] }
      }
      // Koperta pełnego sukcesu i koperta częściowa zawsze niosą `data` (kontrakt §2).
      if (envelope.code === 0 || envelope.code === 102) {
        const payload = envelope.data as { success_count: number; errors: string[] }
        return {
          successCount: payload.success_count,
          errors: envelope.code === 102 ? payload.errors : [],
        }
      }
      throw new ApiError(envelope.code, envelope.message ?? '', response.status)
    },
    onSettled: () => invalidateFiles(queryClient),
  })
}
