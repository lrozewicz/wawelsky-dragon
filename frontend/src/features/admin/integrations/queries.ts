/**
 * Zapytania i mutacje integracji SharePoint (kontrakt WP E4-3c §1).
 * Wzór: `features/admin/queries.ts` — kopertę WD rozpakowuje `wdCall`, a mutacje
 * unieważniają właściwy prefiks kluczy, żeby listy odświeżyły się po zapisie.
 */

import { queryOptions, useMutation, useQueryClient } from '@tanstack/react-query'
import type { QueryClient } from '@tanstack/react-query'

import { api } from '../../../api/client'
import type { components } from '../../../api/schema.gen'

import { wdCall } from '../wdClient'

export type Integration = components['schemas']['Integration']
export type IntegrationRun = components['schemas']['IntegrationRun']
export type IntegrationEvent = components['schemas']['IntegrationEvent']
export type IntegrationDrive = components['schemas']['IntegrationDrive']
export type IntegrationStatus = components['schemas']['IntegrationStatus']
export type ConnectionTest = components['schemas']['ConnectionTest']

/** Rozmiar strony listy integracji (`GET /integrations`) — kontrakt §1. */
export const INTEGRATIONS_PAGE_SIZE = 100

/** Odstęp odpytywania statusu trwającego przebiegu — kontrakt §1. */
export const INTEGRATION_POLL_MS = 3000

/** Rozmiar pierwszej strony historii przebiegów (kontrakt §1: `limit 20`). */
const RUNS_PAGE_SIZE = 20

/** Rozmiar strony zdarzeń przebiegu (pobrania ręczne i kolejne strony kursora). */
const EVENTS_PAGE_SIZE = 100

/** Strona listy integracji — kształt `Page_Integration_` z odpowiedzi `GET /integrations`. */
type IntegrationsPage = components['schemas']['Page_Integration_']
/** Strona kursorowa przebiegów — kształt `CursorPage_IntegrationRun_`. */
type RunsPage = components['schemas']['CursorPage_IntegrationRun_']
/** Strona kursorowa zdarzeń — kształt `CursorPage_IntegrationEvent_`. */
type EventsPage = components['schemas']['CursorPage_IntegrationEvent_']

export const integrationKeys = {
  all: ['admin', 'integrations'] as const,
  list: ['admin', 'integrations', 'list'] as const,
  detail: (id: number) => ['admin', 'integrations', 'detail', id] as const,
  status: (id: number) => ['admin', 'integrations', 'detail', id, 'status'] as const,
  drives: (id: number) => ['admin', 'integrations', 'detail', id, 'drives'] as const,
  runs: (id: number) => ['admin', 'integrations', 'detail', id, 'runs'] as const,
  events: (runId: number, level: string) =>
    ['admin', 'integrations', 'events', runId, level] as const,
}

/** Lista integracji: pierwsza strona w rozmiarze `INTEGRATIONS_PAGE_SIZE`, wynik `items`. */
export function integrationsListQueryOptions() {
  return queryOptions({
    queryKey: integrationKeys.list,
    queryFn: async () =>
      (
        await wdCall<IntegrationsPage>(
          api.GET('/api/wd/v1/integrations', {
            params: { query: { page: 1, page_size: INTEGRATIONS_PAGE_SIZE } },
          }),
        )
      ).items,
  })
}

/** Pojedyncza integracja (bez sekretu — odpowiedź niesie tylko `client_secret_masked`). */
export function integrationQueryOptions(id: number) {
  return queryOptions({
    queryKey: integrationKeys.detail(id),
    queryFn: () =>
      wdCall<Integration>(api.GET('/api/wd/v1/integrations/{id}', { params: { path: { id } } })),
  })
}

/**
 * Stan integracji — odpytywany co `INTEGRATION_POLL_MS`, dopóki przebieg jest aktywny
 * (`is_running` albo status `running`/`queued`); inaczej bez odpytywania.
 */
export function integrationStatusQueryOptions(id: number) {
  return queryOptions({
    queryKey: integrationKeys.status(id),
    queryFn: () =>
      wdCall<IntegrationStatus>(
        api.GET('/api/wd/v1/integrations/{integration_id}/status', {
          params: { path: { integration_id: id } },
        }),
      ),
    refetchInterval: (query) => {
      const data = query.state.data
      return data && isActiveRunStatus(data) ? INTEGRATION_POLL_MS : false
    },
  })
}

/** Biblioteki dokumentów integracji; bez `id` nie ma czego pytać. */
export function integrationDrivesQueryOptions(id: number) {
  return queryOptions({
    queryKey: integrationKeys.drives(id),
    enabled: id > 0,
    queryFn: async () =>
      (
        await wdCall<{ items: IntegrationDrive[] }>(
          api.GET('/api/wd/v1/integrations/{integration_id}/drives', {
            params: { path: { integration_id: id } },
          }),
        )
      ).items,
  })
}

/** Pierwsza strona historii przebiegów (malejąco po `id`) wraz z kursorem. */
export function integrationRunsQueryOptions(id: number) {
  return queryOptions({
    queryKey: integrationKeys.runs(id),
    queryFn: () =>
      wdCall<RunsPage>(
        api.GET('/api/wd/v1/integrations/{integration_id}/runs', {
          params: { path: { integration_id: id }, query: { limit: RUNS_PAGE_SIZE } },
        }),
      ),
  })
}

/**
 * Zdarzenia przebiegu (rosnąco po `id`); `afterId` podaje wołający przy doładowaniu kursora.
 * Schemat API zna poziomy `info | warn | error`, a kontrakt mówi o `warning` — wartość z UI
 * przepuszczamy dosłownie (nieznany poziom odfiltruje się do pustej listy).
 */
export function runEventsQueryOptions(runId: number, level: string, afterId?: number) {
  return queryOptions({
    queryKey: integrationKeys.events(runId, level),
    queryFn: () =>
      wdCall<EventsPage>(
        api.GET('/api/wd/v1/runs/{run_id}/events', {
          params: {
            path: { run_id: runId },
            query: {
              level: level === '' ? undefined : (level as 'info' | 'warn' | 'error'),
              limit: EVENTS_PAGE_SIZE,
              after_id: afterId,
            },
          },
        }),
      ),
  })
}

function invalidateIntegrations(queryClient: QueryClient): void {
  void queryClient.invalidateQueries({ queryKey: integrationKeys.all })
}

/** Klucz zdarzenia `['admin','integrations','events', runId, level]` dla przebiegu z `runIds`. */
function isEventsKeyOfRuns(key: readonly unknown[], runIds: ReadonlySet<number>): boolean {
  return (
    key[0] === 'admin' &&
    key[1] === 'integrations' &&
    key[2] === 'events' &&
    runIds.has(key[3] as number)
  )
}

/** Unieważnia status, przebiegi i listę — po zleceniu/anulowaniu przebiegu zmienia się wszystko. */
function invalidateRunState(queryClient: QueryClient, id: number): void {
  void queryClient.invalidateQueries({ queryKey: integrationKeys.status(id) })
  void queryClient.invalidateQueries({ queryKey: integrationKeys.runs(id) })
  void queryClient.invalidateQueries({ queryKey: integrationKeys.list })
}

export function useCreateIntegration() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: components['schemas']['IntegrationCreateRequest']) =>
      wdCall<Integration>(api.POST('/api/wd/v1/integrations', { body })),
    onSuccess: () => invalidateIntegrations(queryClient),
  })
}

export function useUpdateIntegration(id: number) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: components['schemas']['IntegrationUpdateRequest']) =>
      wdCall<Integration>(
        api.PATCH('/api/wd/v1/integrations/{id}', { params: { path: { id } }, body }),
      ),
    onSuccess: () => invalidateIntegrations(queryClient),
  })
}

export function useDeleteIntegration() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: number) =>
      wdCall<void>(api.DELETE('/api/wd/v1/integrations/{id}', { params: { path: { id } } })),
    onSuccess: async (_data, id) => {
      // Zdarzenia wiszą pod przebiegiem, nie pod integracją — id przebiegów bierzemy z cache.
      const runs = queryClient.getQueryData<{ items: { id: number }[] }>(integrationKeys.runs(id))
      const runIds = new Set((runs?.items ?? []).map((run) => run.id))
      // Najpierw przerywamy loty (status odpytuje w pętli), potem wyrzucamy z cache cały zasób:
      // prefiks detalu niesie szczegóły, status, biblioteki i przebiegi. Lista odświeża się bez
      // dociągania tras usuniętej integracji (WNIOSEK E4-3d).
      await queryClient.cancelQueries({ queryKey: integrationKeys.detail(id) })
      queryClient.removeQueries({ queryKey: integrationKeys.detail(id) })
      queryClient.removeQueries({
        predicate: (query) => isEventsKeyOfRuns(query.queryKey, runIds),
      })
      void queryClient.invalidateQueries({ queryKey: integrationKeys.list })
    },
  })
}

/** Test połączenia przed zapisem — wynik zostaje w `mutation.data`, nie trafia do cache Query. */
export function useTestConnection() {
  return useMutation({
    mutationFn: (body: components['schemas']['ConnectionTestRequest']) =>
      wdCall<ConnectionTest>(api.POST('/api/wd/v1/integrations/test', { body })),
  })
}

/** Test połączenia zapisanej integracji; ciało (nadpisania) może być puste. */
export function useTestSavedConnection(id: number) {
  return useMutation({
    mutationFn: (body: components['schemas']['SavedConnectionTestRequest']) =>
      wdCall<ConnectionTest>(
        api.POST('/api/wd/v1/integrations/{id}/test', { params: { path: { id } }, body }),
      ),
  })
}

export function useSyncIntegration(id: number) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (vars: { full: boolean }) =>
      wdCall<components['schemas']['SyncQueued']>(
        api.POST('/api/wd/v1/integrations/{integration_id}/sync', {
          params: { path: { integration_id: id }, query: { full: vars.full } },
        }),
      ),
    onSuccess: () => invalidateRunState(queryClient, id),
  })
}

export function useCancelIntegration(id: number) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () =>
      wdCall<components['schemas']['CancelResult']>(
        api.POST('/api/wd/v1/integrations/{integration_id}/cancel', {
          params: { path: { integration_id: id } },
        }),
      ),
    onSuccess: () => invalidateRunState(queryClient, id),
  })
}

/** Trwa przebieg, gdy backend mówi `is_running` albo ostatni przebieg jest `running`/`queued`. */
export function isActiveRunStatus(s: {
  is_running: boolean
  latest_run: { status: string } | null
}): boolean {
  return s.is_running || s.latest_run?.status === 'running' || s.latest_run?.status === 'queued'
}
