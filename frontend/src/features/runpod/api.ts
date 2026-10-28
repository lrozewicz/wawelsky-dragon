/**
 * Zapytania i mutacje RunPod (`/api/wd/v1/runpod/*`): klucz API, katalog GPU, preflight parsowania
 * i wdrożenia modeli na GPU w chmurze. Kopertę WD rozpakowuje `wdCall`; błąd 409 `gpu_unavailable`
 * niesie w `details.alternatives` GPU o tym samym lub większym VRAM.
 */

import { queryOptions, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api } from '../../api/client'
import type { components } from '../../api/schema.gen'
import { WdApiError, wdCall } from '../admin/wdClient'

export type RunpodKeyStatus = components['schemas']['KeyStatus']
export type HostedModel = components['schemas']['HostedModelView']
export type RunpodGpu = components['schemas']['GpuView']
export type GpuCatalog = components['schemas']['GpuCatalog']
export type RunpodDeployment = components['schemas']['Deployment']
export type RunpodPreflight = components['schemas']['Preflight']
export type ParseTarget = components['schemas']['ParseRequest']

export type GpuFilters = {
  model: string
  cloud: 'SECURE' | 'COMMUNITY'
  minVram?: number
  maxVram?: number
  region?: string
  country?: string
  onlyAvailable?: boolean
}

/** Odpytywanie wdrożenia, dopóki trwa (zmiana stanu co kilka sekund). */
export const DEPLOYMENT_POLL_MS = 4000

export const TERMINAL_STATUSES = ['terminated', 'failed'] as const

export function isTerminal(status: string): boolean {
  return (TERMINAL_STATUSES as readonly string[]).includes(status)
}

export const runpodKeys = {
  all: ['runpod'] as const,
  key: ['runpod', 'key'] as const,
  models: ['runpod', 'models'] as const,
  gpus: (filters: GpuFilters) => ['runpod', 'gpus', filters] as const,
  deployments: ['runpod', 'deployments'] as const,
  deployment: (id: string) => ['runpod', 'deployments', id] as const,
}

export function keyQueryOptions() {
  return queryOptions({
    queryKey: runpodKeys.key,
    queryFn: () => wdCall<RunpodKeyStatus>(api.GET('/api/wd/v1/runpod/key')),
  })
}

export function modelsQueryOptions() {
  return queryOptions({
    queryKey: runpodKeys.models,
    queryFn: async () =>
      (await wdCall<{ items: HostedModel[] }>(api.GET('/api/wd/v1/runpod/models'))).items,
  })
}

export function gpusQueryOptions(filters: GpuFilters) {
  return queryOptions({
    queryKey: runpodKeys.gpus(filters),
    queryFn: () =>
      wdCall<GpuCatalog>(
        api.GET('/api/wd/v1/runpod/gpus', {
          params: {
            query: {
              model: filters.model,
              cloud: filters.cloud,
              min_vram: filters.minVram,
              max_vram: filters.maxVram,
              region: filters.region || undefined,
              country: filters.country || undefined,
              only_available: filters.onlyAvailable ?? false,
            },
          },
        }),
      ),
    retry: false,
    staleTime: 15_000,
  })
}

/** Lista wdrożeń; odświeżana co `DEPLOYMENT_POLL_MS`, dopóki któreś trwa. */
export function deploymentsQueryOptions() {
  return queryOptions({
    queryKey: runpodKeys.deployments,
    queryFn: async () =>
      (await wdCall<{ items: RunpodDeployment[] }>(api.GET('/api/wd/v1/runpod/deployments'))).items,
    refetchInterval: (query) =>
      query.state.data?.some((d) => d.active) === true ? DEPLOYMENT_POLL_MS : false,
  })
}

export function useDeployment(id: string | null) {
  return useQuery({
    queryKey: runpodKeys.deployment(id ?? ''),
    queryFn: () =>
      wdCall<RunpodDeployment>(
        api.GET('/api/wd/v1/runpod/deployments/{deployment_id}', {
          params: { path: { deployment_id: id as string } },
        }),
      ),
    enabled: id !== null,
    refetchInterval: (query) => {
      const data = query.state.data
      return data !== undefined && isTerminal(data.status) ? false : DEPLOYMENT_POLL_MS
    },
  })
}

export function useSaveKey() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (apiKey: string) =>
      wdCall<RunpodKeyStatus>(api.PUT('/api/wd/v1/runpod/key', { body: { api_key: apiKey } })),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: runpodKeys.all }),
  })
}

export function useDeleteKey() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => wdCall<undefined>(api.DELETE('/api/wd/v1/runpod/key')),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: runpodKeys.all }),
  })
}

export type DeployInput = {
  model: string
  gpuId: string
  cloud: 'SECURE' | 'COMMUNITY'
  region?: string
  country?: string
  parse?: ParseTarget[]
}

export function useDeploy() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (input: DeployInput) =>
      wdCall<RunpodDeployment>(
        api.POST('/api/wd/v1/runpod/deployments', {
          body: {
            model: input.model,
            gpu_id: input.gpuId,
            cloud: input.cloud,
            region: input.region || null,
            country: input.country || null,
            parse: input.parse ?? [],
          },
        }),
      ),
    onSettled: () => queryClient.invalidateQueries({ queryKey: runpodKeys.deployments }),
  })
}

export function useTerminate() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: string) =>
      wdCall<RunpodDeployment>(
        api.DELETE('/api/wd/v1/runpod/deployments/{deployment_id}', {
          params: { path: { deployment_id: id } },
        }),
      ),
    onSettled: () => queryClient.invalidateQueries({ queryKey: runpodKeys.all }),
  })
}

/** Czyści historię: backend usuwa z listy tylko wdrożenia `terminated` i `failed`. */
export function useClearHistory() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => wdCall<{ deleted: number }>(api.DELETE('/api/wd/v1/runpod/deployments')),
    onSettled: () => queryClient.invalidateQueries({ queryKey: runpodKeys.deployments }),
  })
}

export function useQueueParse() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (input: { id: string; target: ParseTarget }) =>
      wdCall<RunpodDeployment>(
        api.POST('/api/wd/v1/runpod/deployments/{deployment_id}/parse', {
          params: { path: { deployment_id: input.id } },
          body: input.target,
        }),
      ),
    onSettled: () => queryClient.invalidateQueries({ queryKey: runpodKeys.deployments }),
  })
}

/** Wołane przed startem parsowania; błąd sieci/uprawnień = „nie blokuj” (straż jest po stronie workera). */
export async function runpodPreflight(
  datasetId: string,
  documentIds: string[],
): Promise<RunpodPreflight | null> {
  try {
    return await wdCall<RunpodPreflight>(
      api.POST('/api/wd/v1/runpod/preflight', {
        body: { dataset_id: datasetId, document_ids: documentIds },
      }),
    )
  } catch {
    return null
  }
}

/** Alternatywne GPU z odpowiedzi 409 `gpu_unavailable` (pusta lista, gdy brak). */
export function alternativesOf(error: unknown): RunpodGpu[] {
  if (!(error instanceof WdApiError) || error.code !== 'gpu_unavailable') return []
  const raw = error.details?.alternatives
  return Array.isArray(raw) ? (raw as RunpodGpu[]) : []
}
