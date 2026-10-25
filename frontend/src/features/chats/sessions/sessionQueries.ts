/**
 * Sesje czatu (kontrakt WP E3-5b §T1): lista, szczegół i mutacje (zmiana nazwy, usuwanie,
 * opinia o wiadomości). Wywołania przez `api`/`apiCall`, listę rozpakowuje `unwrapList('sessions', …)`.
 * Każda mutacja unieważnia `sessionKeys.all(chatId)` (opinia — `sessionKeys.detail`).
 */

import { queryOptions, useMutation, useQueryClient } from '@tanstack/react-query'
import type { QueryClient } from '@tanstack/react-query'

import { api, apiCall } from '../../../api/client'
import { unwrapList } from '../../../api/lists'
import type { components } from '../../../api/schema.gen'

export type Session = components['schemas']['Session']
export type BulkDeleteResult = components['schemas']['BulkDeleteResult']

export const sessionKeys = {
  all: (chatId: string) => ['chats', 'sessions', chatId] as const,
  list: (chatId: string) => ['chats', 'sessions', chatId, 'list'] as const,
  detail: (chatId: string, sessionId: string) =>
    ['chats', 'sessions', chatId, 'detail', sessionId] as const,
}

/** Lista sesji czatu: strona 1000 (wszystkie), najświeższe pierwsze — na potrzebę panelu rozmów. */
export function sessionsListQueryOptions(chatId: string) {
  return queryOptions({
    queryKey: sessionKeys.list(chatId),
    queryFn: async () => {
      const { data, error, response } = await api.GET('/api/v1/chats/{chat_id}/sessions', {
        params: {
          path: { chat_id: chatId },
          query: { page_size: 1000, orderby: 'update_time', desc: true },
        },
      })
      return unwrapList<Session>('sessions', response.ok ? data : error, response.status).items
    },
  })
}

export function sessionQueryOptions(chatId: string, sessionId: string) {
  return queryOptions({
    queryKey: sessionKeys.detail(chatId, sessionId),
    queryFn: () =>
      apiCall<Session>(
        api.GET('/api/v1/chats/{chat_id}/sessions/{session_id}', {
          params: { path: { chat_id: chatId, session_id: sessionId } },
        }),
      ),
  })
}

function invalidateSessions(queryClient: QueryClient, chatId: string): void {
  void queryClient.invalidateQueries({ queryKey: sessionKeys.all(chatId) })
}

/** Zmiana nazwy sesji: PATCH niesie samo `{name}` (kontrakt API wymaga tego klucza). */
export function useRenameSession(chatId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ sessionId, name }: { sessionId: string; name: string }) =>
      apiCall<Session>(
        api.PATCH('/api/v1/chats/{chat_id}/sessions/{session_id}', {
          params: { path: { chat_id: chatId, session_id: sessionId } },
          body: { name },
        }),
      ),
    onSuccess: () => invalidateSessions(queryClient, chatId),
  })
}

/** Usuwanie masowe: ciało to `{ids}`, `delete_all` zostaje na domyślnej wartości backendu. */
export function useDeleteSessions(chatId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (ids: string[]) =>
      apiCall<BulkDeleteResult>(
        api.DELETE('/api/v1/chats/{chat_id}/sessions', {
          params: { path: { chat_id: chatId } },
          body: { ids } as unknown as components['schemas']['DeleteIdsRequest'],
        }),
      ),
    onSuccess: () => invalidateSessions(queryClient, chatId),
  })
}

/** Opinia o wiadomości assistant: `thumbup` wymagany, `feedback` to uzasadnienie lub `null`. */
export function useMessageFeedback(chatId: string, sessionId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({
      messageId,
      thumbup,
      feedback,
    }: {
      messageId: string
      thumbup: boolean
      feedback: string | null
    }) =>
      apiCall<Session>(
        api.PUT('/api/v1/chats/{chat_id}/sessions/{session_id}/messages/{message_id}/feedback', {
          params: {
            path: { chat_id: chatId, session_id: sessionId, message_id: messageId },
          },
          body: { thumbup, feedback },
        }),
      ),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: sessionKeys.detail(chatId, sessionId),
      })
    },
  })
}
