/**
 * Panel administracyjny (kontrakt WP E3-6c2 §3): zapytania i mutacje tras wd.
 * Wzór: `features/chats/queries.ts` i `features/datasets/queries.ts`, ale kopertę
 * rozpakowuje `wdCall` (trasy wd nie mają pola `code`). Każda mutacja unieważnia
 * właściwy prefiks, żeby listy odświeżyły się po zapisie.
 */

import { keepPreviousData, queryOptions, useMutation, useQueryClient } from '@tanstack/react-query'
import type { QueryClient } from '@tanstack/react-query'

import { api } from '../../api/client'
import type { components } from '../../api/schema.gen'

import { STATUS_REFETCH_MS } from './constants'
import { wdCall } from './wdClient'

export type WdUser = components['schemas']['WdUser']
export type ApiKey = components['schemas']['ApiKey']
export type ApiKeyCreated = components['schemas']['ApiKeyCreated']
export type AssistantGrant = components['schemas']['AssistantGrant']
export type Stats = components['schemas']['Stats']
export type SystemHealthz = components['schemas']['SystemHealthz']

/** Strona listy użytkowników — kształt `Page_WdUser_` z odpowiedzi `GET /users`. */
export type UsersPage = { items: WdUser[]; total: number; page: number; page_size: number }

export const adminKeys = {
  all: ['admin'] as const,
  /** Prefiks list użytkowników — unieważniany po każdej zmianie konta. */
  users: ['admin', 'users'] as const,
  usersList: (p: { page: number; pageSize: number; q: string }) =>
    ['admin', 'users', 'list', p] as const,
  apiKeys: (userId: string) => ['admin', 'users', userId, 'api-keys'] as const,
  grants: (email: string) => ['admin', 'access', email] as const,
  stats: ['admin', 'stats'] as const,
  healthz: ['admin', 'healthz'] as const,
}

export function usersListQueryOptions(p: { page: number; pageSize: number; q: string }) {
  return queryOptions({
    queryKey: adminKeys.usersList(p),
    queryFn: () =>
      wdCall<UsersPage>(
        api.GET('/api/wd/v1/users', {
          // Puste `q` pomijamy — backend traktuje brak filtra inaczej niż pusty łańcuch.
          params: {
            query: { page: p.page, page_size: p.pageSize, q: p.q === '' ? undefined : p.q },
          },
        }),
      ),
    // Paginacja bez migotania: podczas pobierania nowej strony zostaje poprzednia, więc
    // `total` nie spada do 0 i `DataGrid` nie klampuje `page` z powrotem na pierwszą.
    placeholderData: keepPreviousData,
  })
}

export function apiKeysQueryOptions(userId: string) {
  return queryOptions({
    queryKey: adminKeys.apiKeys(userId),
    queryFn: async () =>
      (
        await wdCall<{ items: ApiKey[] }>(
          api.GET('/api/wd/v1/users/{user_id}/api-keys', {
            params: { path: { user_id: userId } },
          }),
        )
      ).items,
  })
}

export function grantsQueryOptions(email: string) {
  return queryOptions({
    queryKey: adminKeys.grants(email),
    // Bez e-maila nie ma czego pytać (pole wybiera użytkownika).
    enabled: email !== '',
    queryFn: async () =>
      (
        await wdCall<{ items: AssistantGrant[] }>(
          api.GET('/api/wd/v1/access/assistants', { params: { query: { email } } }),
        )
      ).items,
  })
}

export function statsQueryOptions() {
  return queryOptions({
    queryKey: adminKeys.stats,
    queryFn: () => wdCall<Stats>(api.GET('/api/wd/v1/stats')),
    refetchInterval: STATUS_REFETCH_MS,
  })
}

/**
 * `/api/v1/system/healthz` to jedyna trasa bez koperty — zwraca surowe ciało.
 * Przy `!response.ok` (np. 500 z nieosiągalnym komponentem) rzucamy, żeby karta pokazała błąd.
 */
export function healthzQueryOptions() {
  return queryOptions({
    queryKey: adminKeys.healthz,
    queryFn: async () => {
      const { data, response } = await api.GET('/api/v1/system/healthz')
      if (!response.ok) throw new Error('healthz')
      return data as SystemHealthz
    },
    refetchInterval: STATUS_REFETCH_MS,
  })
}

function invalidateUsers(queryClient: QueryClient): void {
  void queryClient.invalidateQueries({ queryKey: adminKeys.users })
}

export function useCreateUser() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: components['schemas']['UserCreateRequest']) =>
      wdCall<WdUser>(api.POST('/api/wd/v1/users', { body })),
    onSuccess: () => invalidateUsers(queryClient),
  })
}

export function useUpdateUser() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (vars: { id: string; body: components['schemas']['UserUpdateRequest'] }) =>
      wdCall<WdUser>(
        api.PATCH('/api/wd/v1/users/{user_id}', {
          params: { path: { user_id: vars.id } },
          body: vars.body,
        }),
      ),
    onSuccess: () => invalidateUsers(queryClient),
  })
}

export function useSetUserActive() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (vars: { id: string; active: boolean }) =>
      wdCall<WdUser>(
        vars.active
          ? api.POST('/api/wd/v1/users/{user_id}/activate', {
              params: { path: { user_id: vars.id } },
            })
          : api.POST('/api/wd/v1/users/{user_id}/deactivate', {
              params: { path: { user_id: vars.id } },
            }),
      ),
    onSuccess: () => invalidateUsers(queryClient),
  })
}

export function useSetPassword() {
  return useMutation({
    mutationFn: (vars: { id: string; newPassword: string }) =>
      wdCall<void>(
        api.POST('/api/wd/v1/users/{user_id}/password', {
          params: { path: { user_id: vars.id } },
          body: { new_password: vars.newPassword },
        }),
      ),
  })
}

export function useDeleteUser() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (vars: { id: string; mode: 'transfer' | 'cascade' }) =>
      wdCall<void>(
        api.DELETE('/api/wd/v1/users/{user_id}', {
          params: { path: { user_id: vars.id }, query: { mode: vars.mode } },
        }),
      ),
    onSuccess: () => invalidateUsers(queryClient),
  })
}

/**
 * Tworzy klucz API. Token jest jawny TYLKO w tej odpowiedzi — zostaje w `mutation.data`,
 * nie trafia do cache Query (żadnego `setQueryData`); wołający woła `mutation.reset()` po zamknięciu.
 */
export function useCreateApiKey(userId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (vars: { name?: string; expires_at?: string }) =>
      wdCall<ApiKeyCreated>(
        api.POST('/api/wd/v1/users/{user_id}/api-keys', {
          params: { path: { user_id: userId } },
          // Brak daty (`undefined`) znika w JSON — klucz bezterminowy (K14 §3 p. 1).
          body: { name: vars.name, expires_at: vars.expires_at },
        }),
      ),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: adminKeys.apiKeys(userId) })
    },
  })
}

export function useDeleteApiKey(userId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (keyId: string) =>
      wdCall<void>(
        api.DELETE('/api/wd/v1/users/{user_id}/api-keys/{key_id}', {
          params: { path: { user_id: userId, key_id: keyId } },
        }),
      ),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: adminKeys.apiKeys(userId) })
    },
  })
}

export function useReplaceGrants() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (vars: { email: string; chatIds: string[] }) =>
      wdCall<void>(
        api.PUT('/api/wd/v1/access/assistants', {
          body: { email: vars.email, chat_ids: vars.chatIds },
        }),
      ),
    onSuccess: (_result, vars) => {
      void queryClient.invalidateQueries({ queryKey: adminKeys.grants(vars.email) })
    },
  })
}
