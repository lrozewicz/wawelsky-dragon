/**
 * Zapytania i mutacje sekcji Ustawień (kontrakt WP E3-6c1 §2): profil, klucze API i rejestr
 * modeli. Kopertę RAGFlow (`code !== 0` także przy HTTP 200) rozpakowuje `apiCall`.
 * Wzór: `features/admin/queries.ts`.
 */

import { queryOptions, useMutation, useQueryClient } from '@tanstack/react-query'
import type { QueryClient } from '@tanstack/react-query'

import { api, apiCall } from '../../api/client'
import type { components } from '../../api/schema.gen'

export type Me = components['schemas']['User']
export type ApiToken = components['schemas']['ApiToken']
export type CreatedApiToken = components['schemas']['CreatedApiToken']
export type RegistryModel = components['schemas']['Model']

/** Klucz profilu — ten sam, którego używa `features/auth/authState.ts`. */
const ME_KEY = ['me'] as const

/** Klucz modeli domyślnych — `modelsQueryOptions()` z `features/models/queries.ts`. */
const DEFAULT_MODELS_KEY = ['models', 'me'] as const

/** Liczba znaków tokenu widoczna z przodu i z tyłu maski (kontrakt §2). */
const MASK_HEAD = 12
const MASK_TAIL = 4

export const settingsKeys = {
  all: ['settings'] as const,
  tokens: ['settings', 'tokens'] as const,
  registry: ['settings', 'registry'] as const,
  providers: ['settings', 'providers'] as const,
  instances: ['settings', 'instances'] as const,
  instanceList: ['settings', 'instances', 'list'] as const,
  instanceModels: (id: string) => ['settings', 'instances', id, 'models'] as const,
  supported: (id: string) => ['settings', 'instances', id, 'supported'] as const,
}

/**
 * Maska tokenu do wyświetlenia: pierwsze 12 znaków + `…` + ostatnie 4.
 * Tokeny nie dłuższe niż 16 znaków zostają bez zmian (nie ma czego skracać).
 */
export function maskToken(token: string): string {
  if (token.length <= MASK_HEAD + MASK_TAIL) return token
  return `${token.slice(0, MASK_HEAD)}…${token.slice(-MASK_TAIL)}`
}

export function meQueryOptions() {
  return queryOptions({
    queryKey: ME_KEY,
    queryFn: () => apiCall<Me>(api.GET('/api/v1/users/me')),
  })
}

export function tokensQueryOptions() {
  return queryOptions({
    queryKey: settingsKeys.tokens,
    queryFn: () => apiCall<ApiToken[]>(api.GET('/api/v1/system/tokens')),
  })
}

export function registryQueryOptions() {
  return queryOptions({
    queryKey: settingsKeys.registry,
    queryFn: () => apiCall<RegistryModel[]>(api.GET('/api/v1/models')),
  })
}

function invalidate(queryClient: QueryClient, queryKey: readonly unknown[]): void {
  void queryClient.invalidateQueries({ queryKey })
}

export function useUpdateMe() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: components['schemas']['UpdateMeRequest']) =>
      apiCall<void>(api.PATCH('/api/v1/users/me', { body })),
    onSuccess: () => invalidate(queryClient, ME_KEY),
  })
}

export function useUpdateDefaultModels() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: components['schemas']['UpdateDefaultModelsRequest']) =>
      apiCall<void>(api.PATCH('/api/v1/users/me/models', { body })),
    onSuccess: () => invalidate(queryClient, DEFAULT_MODELS_KEY),
  })
}

/**
 * Tworzy klucz API. Token jest jawny TYLKO w tej odpowiedzi — zostaje w `mutation.data`
 * i nie trafia do cache Query (żadnego `setQueryData`); wołający woła `reset()` po zamknięciu
 * podglądu. Wzór: `features/admin/users/ApiKeysDialog.tsx`.
 */
export function useCreateToken() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (vars: { name?: string }) =>
      apiCall<CreatedApiToken>(
        api.POST('/api/v1/system/tokens', { params: { query: { name: vars.name } } }),
      ),
    onSuccess: () => invalidate(queryClient, settingsKeys.tokens),
  })
}

export function useDeleteToken() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (token: string) =>
      apiCall<boolean>(
        api.DELETE('/api/v1/system/tokens/{token}', { params: { path: { token } } }),
      ),
    onSuccess: () => invalidate(queryClient, settingsKeys.tokens),
  })
}
