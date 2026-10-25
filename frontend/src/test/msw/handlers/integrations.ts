import { HttpResponse, http } from 'msw'
import type { HttpHandler } from 'msw'

import type { components } from '../../../api/schema.gen'

import { apiUrl } from './common'

// Typy i fabryki wymagane przez kontrakt WP E4-3c §3.
export type Integration = components['schemas']['Integration']
export type IntegrationRun = components['schemas']['IntegrationRun']
export type IntegrationEvent = components['schemas']['IntegrationEvent']
export type IntegrationStatus = components['schemas']['IntegrationStatus']
export type ConnectionTest = components['schemas']['ConnectionTest']
export type IntegrationCreateRequest = components['schemas']['IntegrationCreateRequest']
export type IntegrationUpdateRequest = components['schemas']['IntegrationUpdateRequest']

/** Znacznik czasu fixtures (ISO 8601) — stały, żeby testy nie zależały od zegara. */
export const INTEGRATIONS_TIMESTAMP = '2025-01-01T00:00:00Z'

/** Rozmiar strony domyślny, gdy wołający nie poda `limit`/`page_size`. */
const DEFAULT_PAGE_SIZE = 20
/** Domyślny rozmiar strony listy integracji (jak `INTEGRATIONS_PAGE_SIZE` z UI). */
const DEFAULT_LIST_PAGE_SIZE = 100

export function makeIntegration(over: Partial<Integration> = {}): Integration {
  return {
    id: 1,
    type: 'sharepoint',
    name: 'Dokumenty zespołu',
    dataset_id: 'ds-1',
    tenant_id: 'tenant-test',
    client_id: 'client-test',
    client_secret_masked: '****abcd',
    site_url: 'https://example.invalid/sites/test',
    site_id: null,
    excluded_library_names: [],
    max_file_size_bytes: 209715200,
    ignored_extensions: [],
    scan_interval_seconds: 300,
    delete_propagation: true,
    is_active: true,
    is_running: false,
    last_sync_at: null,
    last_sync_status: null,
    created_at: INTEGRATIONS_TIMESTAMP,
    updated_at: INTEGRATIONS_TIMESTAMP,
    ...over,
  }
}

export function makeRun(over: Partial<IntegrationRun> = {}): IntegrationRun {
  return {
    id: 1,
    integration_id: 1,
    integration_type: 'sharepoint',
    started_at: INTEGRATIONS_TIMESTAMP,
    finished_at: null,
    status: 'success',
    added: 0,
    updated: 0,
    deleted: 0,
    failed: 0,
    ...over,
  }
}

export function makeEvent(over: Partial<IntegrationEvent> = {}): IntegrationEvent {
  return {
    id: 1,
    run_id: 1,
    integration_id: 1,
    integration_type: 'sharepoint',
    level: 'info',
    message: 'Rozpoczęto przebieg',
    file_path: null,
    drive_id: null,
    drive_name: null,
    created_at: INTEGRATIONS_TIMESTAMP,
    ...over,
  }
}

/** Stan początkowy handlerów — nadpisywany przez `integrationsHandlers(seed)` (kontrakt §3). */
export type IntegrationsSeed = {
  integrations?: Integration[]
  runs?: Record<number, IntegrationRun[]>
  events?: Record<number, IntegrationEvent[]>
}

/** Maska sekretu jak w backendzie: cztery ostatnie znaki poprzedzone gwiazdkami. */
function maskSecret(secret: string): string {
  return `****${secret.slice(-4)}`
}

function positiveInt(value: string | null, fallback: number): number {
  const parsed = Number.parseInt(value ?? '', 10)
  return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback
}

/** Raport testu połączenia: bez Graph (stos testowy) uwierzytelnienie zawsze pada (kontrakt §0). */
function connectionTest(tenantId: string): ConnectionTest {
  if (tenantId === 'bad') {
    return {
      graph_auth: 'failed',
      graph_auth_error: 'Invalid tenant',
      site_resolution: 'skipped',
      dataset_exists: 'skipped',
    }
  }
  return {
    graph_auth: 'ok',
    site_resolution: 'ok',
    site_id: 'site-1',
    site_display_name: 'Witryna testowa',
    drives_visible: 1,
    drives_after_exclusion: 1,
    drive_names: ['Dokumenty'],
    dataset_exists: 'ok',
    dataset_name: 'Zbiór testowy',
  }
}

function cloneRuns(source: Record<number, IntegrationRun[]>): Record<number, IntegrationRun[]> {
  return Object.fromEntries(
    Object.entries(source).map(([id, list]) => [id, list.map((run) => ({ ...run }))]),
  )
}

function cloneEvents(
  source: Record<number, IntegrationEvent[]>,
): Record<number, IntegrationEvent[]> {
  return Object.fromEntries(
    Object.entries(source).map(([id, list]) => [id, list.map((event) => ({ ...event }))]),
  )
}

/** Największe `id` w listach przebiegów/zdarzeń — punkt startowy liczników. */
function maxId(rows: { id: number }[]): number {
  return rows.reduce((max, row) => Math.max(max, row.id), 0)
}

/**
 * Handlery MSW obszaru integracji w kopercie wd (kontrakt §0 i §3): sukces `{data}`, 204 bez ciała,
 * błąd `{error:{code,message}}`. Stan trzymamy w domknięciu — każde wywołanie daje świeży stan,
 * a `server.resetHandlers()` w `src/test/setup.ts` wraca między testami do seedu domyślnego.
 */
export function integrationsHandlers(seed: IntegrationsSeed = {}): HttpHandler[] {
  let integrations = (seed.integrations ?? []).map((row) => ({ ...row }))
  const runs = cloneRuns(seed.runs ?? {})
  const events = cloneEvents(seed.events ?? {})
  let nextIntegrationId = maxId(integrations) + 1

  const find = (id: number) => integrations.find((row) => row.id === id)
  const datasetTaken = (datasetId: string, exceptId?: number) =>
    integrations.some((row) => row.dataset_id === datasetId && row.id !== exceptId)

  const notFound = () =>
    HttpResponse.json(
      { error: { code: 'not_found', message: 'Nie ma takiej integracji' } },
      { status: 404 },
    )
  const conflict = () =>
    HttpResponse.json(
      { error: { code: 'conflict', message: 'Ten dataset ma już integrację' } },
      { status: 409 },
    )

  /** Status integracji z ostatnim przebiegiem z magazynu (malejąco po `id`), albo `null`. */
  const toStatus = (row: Integration): IntegrationStatus => {
    const latest = [...(runs[row.id] ?? [])].sort((a, b) => b.id - a.id)[0]
    return {
      id: row.id,
      is_active: row.is_active,
      is_running: row.is_running,
      last_sync_at: row.last_sync_at,
      last_sync_status: row.last_sync_status,
      latest_run: latest === undefined ? null : { ...latest },
    }
  }

  return [
    // Test połączenia bez zapisu — musi być zarejestrowany przed trasą `:id`.
    http.post(apiUrl('/api/wd/v1/integrations/test'), async ({ request }) => {
      const body = (await request.json()) as components['schemas']['ConnectionTestRequest']
      return HttpResponse.json({ data: connectionTest(body.tenant_id) })
    }),

    http.get(apiUrl('/api/wd/v1/integrations'), ({ request }) => {
      const url = new URL(request.url)
      const page = positiveInt(url.searchParams.get('page'), 1)
      const pageSize = positiveInt(url.searchParams.get('page_size'), DEFAULT_LIST_PAGE_SIZE)
      const sorted = [...integrations].sort((a, b) => b.id - a.id)
      const start = (page - 1) * pageSize
      return HttpResponse.json({
        data: {
          items: sorted.slice(start, start + pageSize),
          total: sorted.length,
          page,
          page_size: pageSize,
        },
      })
    }),

    http.post(apiUrl('/api/wd/v1/integrations'), async ({ request }) => {
      const body = (await request.json()) as IntegrationCreateRequest
      if (datasetTaken(body.dataset_id)) return conflict()

      const created = makeIntegration({
        id: nextIntegrationId,
        name: body.name,
        dataset_id: body.dataset_id,
        tenant_id: body.tenant_id,
        client_id: body.client_id,
        client_secret_masked: maskSecret(body.client_secret),
        site_url: body.site_url,
        excluded_library_names: body.excluded_library_names ?? [],
        ignored_extensions: body.ignored_extensions ?? [],
        max_file_size_bytes: body.max_file_size_bytes,
        scan_interval_seconds: body.scan_interval_seconds,
        delete_propagation: body.delete_propagation,
        is_active: body.is_active,
      })
      nextIntegrationId += 1
      integrations = [...integrations, created]
      return HttpResponse.json({ data: created }, { status: 201 })
    }),

    http.get(apiUrl('/api/wd/v1/integrations/:id'), ({ params }) => {
      const row = find(Number(String(params.id)))
      return row === undefined ? notFound() : HttpResponse.json({ data: row })
    }),

    http.patch(apiUrl('/api/wd/v1/integrations/:id'), async ({ params, request }) => {
      const row = find(Number(String(params.id)))
      if (row === undefined) return notFound()
      const body = (await request.json()) as IntegrationUpdateRequest
      if (body.dataset_id != null && datasetTaken(body.dataset_id, row.id)) return conflict()

      // Puste/pominięte pole = brak zmiany; sekret nadpisujemy tylko, gdy przyszedł niepusty (§0).
      const next: Integration = { ...row }
      if (body.name != null) next.name = body.name
      if (body.dataset_id != null) next.dataset_id = body.dataset_id
      if (body.tenant_id != null) next.tenant_id = body.tenant_id
      if (body.client_id != null) next.client_id = body.client_id
      if (body.site_url != null) next.site_url = body.site_url
      if (body.excluded_library_names != null)
        next.excluded_library_names = body.excluded_library_names
      if (body.ignored_extensions != null) next.ignored_extensions = body.ignored_extensions
      if (body.max_file_size_bytes != null) next.max_file_size_bytes = body.max_file_size_bytes
      if (body.scan_interval_seconds != null)
        next.scan_interval_seconds = body.scan_interval_seconds
      if (body.delete_propagation != null) next.delete_propagation = body.delete_propagation
      if (body.is_active != null) next.is_active = body.is_active
      if (body.client_secret != null && body.client_secret !== '') {
        next.client_secret_masked = maskSecret(body.client_secret)
      }

      integrations = integrations.map((candidate) => (candidate.id === next.id ? next : candidate))
      return HttpResponse.json({ data: next })
    }),

    http.delete(apiUrl('/api/wd/v1/integrations/:id'), ({ params }) => {
      const id = Number(String(params.id))
      if (find(id) === undefined) return notFound()
      integrations = integrations.filter((row) => row.id !== id)
      return new HttpResponse(null, { status: 204 })
    }),

    http.post(apiUrl('/api/wd/v1/integrations/:id/test'), async ({ params, request }) => {
      const row = find(Number(String(params.id)))
      if (row === undefined) return notFound()
      const body = (await request.json().catch(() => null)) as
        components['schemas']['SavedConnectionTestRequest'] | null
      return HttpResponse.json({ data: connectionTest(body?.tenant_id ?? row.tenant_id) })
    }),

    http.post(apiUrl('/api/wd/v1/integrations/:integrationId/sync'), ({ params }) => {
      const row = find(Number(String(params.integrationId)))
      if (row === undefined) return notFound()
      row.is_running = true
      return HttpResponse.json({ data: { queued: true } }, { status: 202 })
    }),

    http.post(apiUrl('/api/wd/v1/integrations/:integrationId/cancel'), ({ params }) => {
      const row = find(Number(String(params.integrationId)))
      if (row === undefined) return notFound()
      row.is_running = false
      return HttpResponse.json({ data: { cancelled: true } })
    }),

    http.get(apiUrl('/api/wd/v1/integrations/:integrationId/status'), ({ params }) => {
      const row = find(Number(String(params.integrationId)))
      return row === undefined ? notFound() : HttpResponse.json({ data: toStatus(row) })
    }),

    // Bez Graph nie znamy bibliotek — domyślnie pusto; testy podają własny handler.
    http.get(apiUrl('/api/wd/v1/integrations/:integrationId/drives'), ({ params }) => {
      const row = find(Number(String(params.integrationId)))
      return row === undefined ? notFound() : HttpResponse.json({ data: { items: [] } })
    }),

    http.get(apiUrl('/api/wd/v1/integrations/:integrationId/runs'), ({ params, request }) => {
      const row = find(Number(String(params.integrationId)))
      if (row === undefined) return notFound()
      const url = new URL(request.url)
      const limit = positiveInt(url.searchParams.get('limit'), DEFAULT_PAGE_SIZE)
      const afterId = url.searchParams.get('after_id')
      const cursor = afterId === null ? null : Number(afterId)
      // Kursor malejąco: `after_id` znaczy „id mniejsze niż ta wartość”.
      const page = [...(runs[row.id] ?? [])]
        .filter((run) => cursor === null || run.id < cursor)
        .sort((a, b) => b.id - a.id)
      const items = page.slice(0, limit)
      const last = items.at(-1)
      const nextAfterId = page.length > items.length && last !== undefined ? last.id : null
      return HttpResponse.json({ data: { items, next_after_id: nextAfterId } })
    }),

    http.get(apiUrl('/api/wd/v1/runs/:runId/events'), ({ params, request }) => {
      const url = new URL(request.url)
      const limit = positiveInt(url.searchParams.get('limit'), DEFAULT_PAGE_SIZE)
      const level = url.searchParams.get('level')
      const afterId = url.searchParams.get('after_id')
      const cursor = afterId === null ? null : Number(afterId)
      // Kursor rosnąco: `after_id` znaczy „id większe niż ta wartość”; brak przebiegu = pusta lista.
      const page = [...(events[Number(String(params.runId))] ?? [])]
        .filter((event) => cursor === null || event.id > cursor)
        .filter((event) => level === null || level === '' || event.level === level)
        .sort((a, b) => a.id - b.id)
      const items = page.slice(0, limit)
      const last = items.at(-1)
      const nextAfterId = page.length > items.length && last !== undefined ? last.id : null
      return HttpResponse.json({ data: { items, next_after_id: nextAfterId } })
    }),
  ]
}
