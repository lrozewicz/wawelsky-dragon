/**
 * Zapytania i mutacje dostawcy modeli (kontrakt WP E3-6c1 §3): instancje dostawcy `PROVIDER`,
 * ich modele oraz rejestr. Trasy zapisu są tylko dla superusera (pilnuje ich backend, K13);
 * UI ukrywa przyciski na podstawie `useIsSuperuser()`.
 */

import { queryOptions, useMutation, useQueryClient } from '@tanstack/react-query'
import type { QueryClient } from '@tanstack/react-query'

import { api, apiCall } from '../../api/client'
import type { components } from '../../api/schema.gen'

import { PROVIDER } from './constants'
import { settingsKeys } from './queries'

export type ProviderInstance = components['schemas']['ProviderInstance']
export type ProviderInstanceDetail = components['schemas']['ProviderInstanceDetail']
export type InstanceModel = components['schemas']['InstanceModel']
export type SupportedModel = components['schemas']['SupportedModel']

/** Ścieżka instancji dostawcy — wspólna dla wszystkich wywołań poniżej. */
const INSTANCE_PATH = { name: PROVIDER } as const

export function instancesQueryOptions() {
  return queryOptions({
    queryKey: settingsKeys.instanceList,
    queryFn: () =>
      apiCall<ProviderInstance[]>(
        api.GET('/api/v1/providers/{name}/instances', { params: { path: INSTANCE_PATH } }),
      ),
  })
}

export function instanceDetailQueryOptions(id: string) {
  return queryOptions({
    queryKey: [...settingsKeys.instances, id],
    queryFn: () =>
      apiCall<ProviderInstanceDetail>(
        api.GET('/api/v1/providers/{name}/instances/{instance}', {
          params: { path: { ...INSTANCE_PATH, instance: id } },
        }),
      ),
  })
}

export function instanceModelsQueryOptions(id: string) {
  return queryOptions({
    queryKey: settingsKeys.instanceModels(id),
    queryFn: () =>
      apiCall<InstanceModel[]>(
        api.GET('/api/v1/providers/{name}/instances/{instance}/models', {
          params: { path: { ...INSTANCE_PATH, instance: id } },
        }),
      ),
  })
}

/** Lista modeli bramki (`supported=true`); pytamy dopiero, gdy dialog importu jest otwarty. */
export function supportedModelsQueryOptions(id: string, enabled: boolean) {
  return queryOptions({
    queryKey: settingsKeys.supported(id),
    queryFn: () =>
      apiCall<SupportedModel[]>(
        api.GET('/api/v1/providers/{name}/instances/{instance}/models', {
          params: { path: { ...INSTANCE_PATH, instance: id }, query: { supported: true } },
        }),
      ),
    staleTime: 0,
    enabled,
  })
}

function invalidate(queryClient: QueryClient, queryKey: readonly unknown[]): void {
  void queryClient.invalidateQueries({ queryKey })
}

export function useCreateInstance() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: components['schemas']['ProviderInstanceCreateRequest']) =>
      apiCall<ProviderInstance>(
        api.POST('/api/v1/providers/{name}/instances', { params: { path: INSTANCE_PATH }, body }),
      ),
    onSuccess: () => invalidate(queryClient, settingsKeys.instanceList),
  })
}

export function useUpdateInstance() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (vars: {
      id: string
      body: components['schemas']['ProviderInstanceUpdateRequest']
    }) =>
      apiCall<ProviderInstanceDetail>(
        api.PUT('/api/v1/providers/{name}/instances/{instance}', {
          params: { path: { ...INSTANCE_PATH, instance: vars.id } },
          body: vars.body,
        }),
      ),
    onSuccess: () => invalidate(queryClient, settingsKeys.instances),
  })
}

export function useDeleteInstances() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (instances: string[]) =>
      apiCall<void>(
        api.DELETE('/api/v1/providers/{name}/instances', {
          params: { path: INSTANCE_PATH },
          body: { instances },
        }),
      ),
    onSuccess: () => {
      invalidate(queryClient, settingsKeys.instances)
      invalidate(queryClient, settingsKeys.registry)
    },
  })
}

/** Sonda `GET {base_url}/models` bramki — nic nie zapisuje, więc niczego nie unieważnia. */
export function useVerifyConnection() {
  return useMutation({
    mutationFn: (body: components['schemas']['ProviderConnectionRequest']) =>
      apiCall<void>(
        api.POST('/api/v1/providers/{name}/connection', {
          params: { path: INSTANCE_PATH },
          body,
        }),
      ),
  })
}

function invalidateModels(queryClient: QueryClient, instanceId: string): void {
  invalidate(queryClient, settingsKeys.instanceModels(instanceId))
  invalidate(queryClient, settingsKeys.registry)
}

export function useAddInstanceModel(instanceId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: components['schemas']['InstanceModelAddRequest']) =>
      apiCall<InstanceModel>(
        api.POST('/api/v1/providers/{name}/instances/{instance}/models', {
          params: { path: { ...INSTANCE_PATH, instance: instanceId } },
          body,
        }),
      ),
    onSuccess: () => invalidateModels(queryClient, instanceId),
  })
}

export function useUpdateInstanceModel(instanceId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (vars: {
      modelName: string
      body: components['schemas']['InstanceModelUpdateRequest']
    }) =>
      apiCall<InstanceModel>(
        api.PATCH('/api/v1/providers/{name}/instances/{instance}/models/{model_name}', {
          params: { path: { ...INSTANCE_PATH, instance: instanceId, model_name: vars.modelName } },
          body: vars.body,
        }),
      ),
    onSuccess: () => invalidateModels(queryClient, instanceId),
  })
}

export function useDeleteInstanceModels(instanceId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (modelNames: string[]) =>
      apiCall<void>(
        api.DELETE('/api/v1/providers/{name}/instances/{instance}/models', {
          params: { path: { ...INSTANCE_PATH, instance: instanceId } },
          body: { model_name: modelNames },
        }),
      ),
    onSuccess: () => invalidateModels(queryClient, instanceId),
  })
}
