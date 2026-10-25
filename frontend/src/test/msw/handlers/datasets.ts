import { HttpResponse, http } from 'msw'
import type { HttpHandler } from 'msw'

import { fixtureIngestionSummary } from './datasetLogs'
import type { FixtureIngestionLog } from './datasetLogs'
import { apiUrl } from './common'
import type { FixtureDataset } from './home'
import { fixtureModels } from './models'

// Podzbiór `DatasetListed` używany przez ustawienia czatu (08 §8.2) — do wyboru bazy wiedzy
// potrzebne są `embedding_model` i `chunk_count`, których karty Home nie czytają.
export type FixtureDatasetListed = FixtureDataset & {
  embedding_model: string
  chunk_count: number
}

export function datasetListed(overrides: Partial<FixtureDatasetListed> = {}): FixtureDatasetListed {
  return {
    id: 'ds-1',
    name: 'Baza testowa',
    description: null,
    document_count: 3,
    embedding_model: fixtureModels.embd_id,
    chunk_count: 12,
    ...overrides,
  }
}

// Trzy bazy dla testów szuflady czatu: `ds-2` ma inny model embeddingu, `ds-3` zero chunków.
export const fixtureChatDatasets: FixtureDatasetListed[] = [
  datasetListed({ id: 'ds-1', name: 'Baza wiedzy' }),
  datasetListed({ id: 'ds-2', name: 'Inny embedding', embedding_model: 'other-embd' }),
  datasetListed({ id: 'ds-3', name: 'Pusta baza', document_count: 0, chunk_count: 0 }),
]

// Odpowiednik `DatasetDetail` z backend/openapi.json (`Dataset` + `connectors` + `size`) —
// odpowiedź GET/PUT /api/v1/datasets/{id}; pola czytane przez layout, konfigurację i logi (08 §7.4).
// Nazwa z kontraktu WP E3-3a (`fixtureDataset`) jest zajęta przez stałą dla kart Home wyżej —
// fabryka szczegółu nazywa się `fixtureDatasetDetail` (wzór: `chatDetail`, `datasetListed`).
export type FixtureDatasetDetail = {
  id: string
  name: string
  description: string | null
  document_count: number
  chunk_count: number
  chunk_method: string
  embedding_model: string
  language: string
  permission: 'me' | 'team'
  parser_config: Record<string, unknown>
  create_time: number
  connectors: unknown[]
  size?: number | null
}

export function fixtureDatasetDetail(
  overrides: Partial<FixtureDatasetDetail> = {},
): FixtureDatasetDetail {
  return {
    id: 'ds-1',
    name: 'Baza testowa',
    description: null,
    document_count: 3,
    chunk_count: 12,
    chunk_method: 'naive',
    embedding_model: fixtureModels.embd_id,
    language: 'Polish',
    permission: 'me',
    parser_config: { chunk_token_num: 128, delimiter: '\n' },
    create_time: 1735689600000,
    connectors: [],
    size: 4096,
    ...overrides,
  }
}

/**
 * Handlery datasetów z pamięcią stanu (wzór `chatsHandlers`): lista, szczegół, CRUD, podsumowanie
 * i logi ingestii (kontrakt WP E3-3a §T1). Każde wywołanie daje świeży magazyn, a
 * `server.resetHandlers()` wraca między testami do stanu z `handlers`.
 * `options.onUpdate` dostaje ciało PUT (testy konfiguracji T4 sprawdzają nim „tylko zmienione pola”),
 * `options.logs` to zawartość `…/ingestions` (domyślnie pusta).
 */
export function datasetHandlers(
  initial: FixtureDatasetDetail[] = [],
  options: {
    logs?: FixtureIngestionLog[]
    onUpdate?: (body: Record<string, unknown>) => void
  } = {},
): HttpHandler[] {
  const store = new Map(initial.map((dataset) => [dataset.id, { ...dataset }]))
  const logs = [...(options.logs ?? [])]
  let nextId = store.size + 1

  const notFound = () => HttpResponse.json({ code: 102, message: 'Dataset not found', data: null })

  return [
    http.get(apiUrl('/api/v1/datasets'), () =>
      HttpResponse.json({
        code: 0,
        message: 'success',
        data: [...store.values()],
        total_datasets: store.size,
      }),
    ),

    http.get(apiUrl('/api/v1/datasets/:datasetId'), ({ params }) => {
      // `apiUrl()` zwraca zwykły string, więc MSW typuje `params.*` jako `string | string[] | undefined`.
      const dataset = store.get(String(params.datasetId))
      return dataset === undefined
        ? notFound()
        : HttpResponse.json({ code: 0, message: 'success', data: dataset })
    }),

    http.post(apiUrl('/api/v1/datasets'), async ({ request }) => {
      const body = (await request.json()) as Partial<FixtureDatasetDetail>
      const created = fixtureDatasetDetail({ ...body, id: `ds-${nextId}` })
      nextId += 1
      store.set(created.id, created)
      return HttpResponse.json({ code: 0, message: 'success', data: created })
    }),

    http.put(apiUrl('/api/v1/datasets/:datasetId'), async ({ request, params }) => {
      const body = (await request.json()) as Record<string, unknown>
      const current = store.get(String(params.datasetId))
      if (current === undefined) return notFound()
      options.onUpdate?.(body)
      const updated = { ...current, ...body } as FixtureDatasetDetail
      store.set(updated.id, updated)
      return HttpResponse.json({ code: 0, message: 'success', data: updated })
    }),

    http.delete(apiUrl('/api/v1/datasets'), async ({ request }) => {
      const body = (await request.json()) as { ids?: string[] }
      const ids = body.ids ?? []
      for (const id of ids) store.delete(id)
      return HttpResponse.json({ code: 0, message: 'success', data: { success_count: ids.length } })
    }),

    // Podsumowanie PRZED `…/ingestions/:logId` — inaczej „summary” zostałoby wzięte za log_id
    // (MSW bierze pierwszy pasujący handler w kolejności rejestracji).
    http.get(apiUrl('/api/v1/datasets/:datasetId/ingestions/summary'), ({ params }) => {
      const dataset = store.get(String(params.datasetId))
      return dataset === undefined
        ? notFound()
        : HttpResponse.json({
            code: 0,
            message: 'success',
            data: fixtureIngestionSummary({
              doc_num: dataset.document_count,
              chunk_num: dataset.chunk_count,
            }),
          })
    }),

    http.get(apiUrl('/api/v1/datasets/:datasetId/ingestions'), ({ params, request }) => {
      const url = new URL(request.url)
      const datasetId = String(params.datasetId)
      // openapi-fetch serializuje tablicę jako powtórzone `operation_status=3`, backend przyjmuje
      // `operation_status[]=3` (kontrakt §Fakty API) — obsługujemy oba kształty.
      const statuses = [
        ...url.searchParams.getAll('operation_status'),
        ...url.searchParams.getAll('operation_status[]'),
      ].flatMap((value) => value.split(','))
      const matched = logs.filter(
        (log) =>
          log.kb_id === datasetId &&
          (statuses.length === 0 || statuses.includes(log.operation_status)),
      )
      const page = Number(url.searchParams.get('page') ?? '1')
      const pageSize = Number(url.searchParams.get('page_size') ?? '10')
      const from = (page - 1) * pageSize
      return HttpResponse.json({
        code: 0,
        message: 'success',
        data: { logs: matched.slice(from, from + pageSize), total: matched.length },
      })
    }),

    http.get(apiUrl('/api/v1/datasets/:datasetId/ingestions/:logId'), ({ params }) => {
      const logId = String(params.logId)
      const log = logs.find((item) => item.id === logId && item.kb_id === String(params.datasetId))
      return log === undefined
        ? HttpResponse.json({ code: 102, message: 'Log not found', data: null })
        : HttpResponse.json({ code: 0, message: 'success', data: log })
    }),
  ]
}

/**
 * Lista baz wiedzy (`GET /api/v1/datasets`) z jawnie podanymi elementami. Domyślny handler w
 * `handlers` zwraca pustą listę (zależne są od tego testy Home) — testy szuflady czatu
 * podmieniają go przez `server.use(...datasetsHandlers(fixtureChatDatasets))`.
 */
export function datasetsHandlers(items: FixtureDatasetListed[]): HttpHandler[] {
  return [
    http.get(apiUrl('/api/v1/datasets'), () =>
      HttpResponse.json({ code: 0, message: 'success', data: items, total_datasets: items.length }),
    ),
  ]
}

/** Pole konfiguracji metadanych w kształcie drutu (kontrakt WP E6-1b §1). */
export type FixtureMetadataField = {
  key: string
  type: 'string'
  description: string | null
  enum: string[] | null
}

/**
 * Handlery metadanych datasetu (kontrakt WP E6-1b §1): GET/PUT `…/metadata/config` z pamięcią
 * stanu per dataset (domyślnie puste listy, `built_in_metadata` poza zakresem UI). `initial`
 * to nasienie `{datasetId: [pola]}`, `options.onUpdate` łapie ciało PUT (testy kolejności zapisu).
 */
export function metadataHandlers(
  initial: Record<string, FixtureMetadataField[]> = {},
  options: {
    onUpdate?: (datasetId: string, body: { metadata?: FixtureMetadataField[] }) => void
  } = {},
): HttpHandler[] {
  const store = new Map(Object.entries(initial))
  return [
    http.get(apiUrl('/api/v1/datasets/:datasetId/metadata/config'), ({ params }) =>
      HttpResponse.json({
        code: 0,
        message: 'success',
        data: { metadata: store.get(String(params.datasetId)) ?? [], built_in_metadata: [] },
      }),
    ),
    http.put(apiUrl('/api/v1/datasets/:datasetId/metadata/config'), async ({ request, params }) => {
      const body = (await request.json()) as { metadata?: FixtureMetadataField[] }
      const metadata = body.metadata ?? []
      store.set(String(params.datasetId), metadata)
      options.onUpdate?.(String(params.datasetId), body)
      return HttpResponse.json({
        code: 0,
        message: 'success',
        data: { metadata, built_in_metadata: [] },
      })
    }),
  ]
}
