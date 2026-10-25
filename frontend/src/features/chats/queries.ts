/**
 * Czaty (08 §7.6, kontrakt WP E3-5a §5): lista, szczegół i mutacje CRUD.
 * Wywołania przez `api`/`apiCall`, listę rozpakowuje `unwrapList('chats', …)`.
 * Każda mutacja unieważnia `chatKeys.all` — lista odświeża się po zapisie.
 */

import { queryOptions, useMutation, useQueryClient } from '@tanstack/react-query'
import type { QueryClient } from '@tanstack/react-query'

import { api, apiCall } from '../../api/client'
import { unwrapList } from '../../api/lists'
import type { components } from '../../api/schema.gen'

export type Chat = components['schemas']['Chat']
export type ChatListItem = components['schemas']['ChatListItem']
export type BulkDeleteResult = components['schemas']['BulkDeleteResult']

export const chatKeys = {
  all: ['chats'] as const,
  list: (params?: { name?: string }) => ['chats', 'list', params ?? {}] as const,
  detail: (id: string) => ['chats', 'detail', id] as const,
}

export function chatsListQueryOptions(params?: { name?: string }) {
  return queryOptions({
    queryKey: chatKeys.list(params),
    queryFn: async () => {
      const { data, error, response } = await api.GET('/api/v1/chats', {
        params: { query: { name: params?.name } },
      })
      return unwrapList<ChatListItem>('chats', response.ok ? data : error, response.status).items
    },
  })
}

export function chatQueryOptions(id: string) {
  return queryOptions({
    queryKey: chatKeys.detail(id),
    queryFn: () =>
      apiCall<Chat>(api.GET('/api/v1/chats/{chat_id}', { params: { path: { chat_id: id } } })),
  })
}

function invalidateChats(queryClient: QueryClient): void {
  void queryClient.invalidateQueries({ queryKey: chatKeys.all })
}

/** Pola tworzenia czatu; `description`/`prologue`/`emptyResponse` wołający bierze z i18n (język UI, K4; K20 §5 p. 3). */
export type CreateChatInput = {
  name: string
  description: string
  prologue: string
  emptyResponse: string
  /** Bazy wybrane w oknie tworzenia (SC-V13-10); do body trafiają jako `dataset_ids` tylko gdy niepuste. */
  datasetIds?: string[]
}

/** Tworzenie czatu: nazwa plus domyślne teksty w języku UI (opis, powitanie i odpowiedź przy
 *  braku wyników, K4/DEC-306 + K20 §5 p. 3/DEC-358); brakujące klucze `prompt_config` uzupełnia
 *  backend wartościami upstream (`apply_prompt_defaults`, chat_validation.py). */
export function useCreateChat() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ name, description, prologue, emptyResponse, datasetIds }: CreateChatInput) =>
      apiCall<Chat>(
        api.POST('/api/v1/chats', {
          // Wygenerowany typ wymaga wszystkich kluczy, choć backend przyjmuje częściowe ciało
          // (jak `UpdateMeRequest` w `_app/route.tsx`).
          body: {
            name,
            description,
            prompt_config: { prologue, empty_response: emptyResponse },
            // `dataset_ids` tylko gdy wybrano bazy (CONTRACT WP V13-2 §4) — brak klucza = czat bez bazy.
            ...(datasetIds !== undefined && datasetIds.length > 0
              ? { dataset_ids: datasetIds }
              : {}),
          } as unknown as components['schemas']['CreateChatRequest'],
        }),
      ),
    onSuccess: () => invalidateChats(queryClient),
  })
}

/** Zmiana czatu: PATCH wysyła wyłącznie zmienione pola (backend scala je z bieżącym stanem). */
export function useUpdateChat(id: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (patch: Record<string, unknown>) =>
      apiCall<Chat>(
        api.PATCH('/api/v1/chats/{chat_id}', {
          params: { path: { chat_id: id } },
          // Typ żądania wymaga znanych kluczy, a wołający buduje łatkę dynamicznie (jak w `_app/route.tsx`).
          body: patch as components['schemas']['UpdateChatRequest'],
        }),
      ),
    onSuccess: () => invalidateChats(queryClient),
  })
}

/** Usuwanie masowe: ciało to `{ids}`, `delete_all` zostaje na domyślnej wartości backendu. */
export function useDeleteChats() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (ids: string[]) =>
      apiCall<BulkDeleteResult>(
        api.DELETE('/api/v1/chats', {
          body: { ids } as unknown as components['schemas']['DeleteIdsRequest'],
        }),
      ),
    onSuccess: () => invalidateChats(queryClient),
  })
}
