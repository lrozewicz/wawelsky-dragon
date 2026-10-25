import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, cleanup, renderHook } from '@testing-library/react'
import { HttpResponse, http } from 'msw'
import type { ReactNode } from 'react'
import { afterEach, describe, expect, it } from 'vitest'

import {
  apiUrl,
  datasetHandlers,
  datasetListed,
  fixtureDatasetDetail,
  fixtureIngestionLog,
  fixtureIngestionSummary,
} from '../../test/msw/handlers'
import { server } from '../../test/msw/server'

import {
  datasetKeys,
  datasetQueryOptions,
  datasetsListQueryOptions,
  ingestionLogQueryOptions,
  ingestionLogsQueryOptions,
  ingestionSummaryQueryOptions,
  useCreateDataset,
  useDeleteDatasets,
  useUpdateDataset,
} from './queries'

afterEach(cleanup)

function createClient(): QueryClient {
  return new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } })
}

function wrapperFor(client: QueryClient) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>
  }
}

const DATASET = fixtureDatasetDetail({ id: 'ds-1', name: 'Alfa' })

describe('datasetsListQueryOptions', () => {
  it('prosi o całą listę (page_size 1000, update_time, malejąco), filtr trafia do zapytania i klucza', async () => {
    const seen: URL[] = []
    const item = datasetListed({ id: 'ds-7', name: 'Beta' })
    server.use(
      http.get(apiUrl('/api/v1/datasets'), ({ request }) => {
        seen.push(new URL(request.url))
        return HttpResponse.json({
          code: 0,
          message: 'success',
          data: [item],
          total_datasets: 1,
        })
      }),
    )
    const items = await createClient().fetchQuery(datasetsListQueryOptions())
    await createClient().fetchQuery(datasetsListQueryOptions({ keywords: 'Beta' }))

    expect(items).toEqual([item])
    expect(seen[0]?.searchParams.get('page_size')).toBe('1000')
    expect(seen[0]?.searchParams.get('orderby')).toBe('update_time')
    expect(seen[0]?.searchParams.get('desc')).toBe('true')
    expect(seen[0]?.searchParams.get('keywords')).toBeNull()
    expect(seen[1]?.searchParams.get('keywords')).toBe('Beta')
    expect(datasetsListQueryOptions({ keywords: 'Beta' }).queryKey).toEqual(
      datasetKeys.list({ keywords: 'Beta' }),
    )
  })

  it('rzuca ApiError przy kopercie code ≠ 0 i przy błędzie HTTP', async () => {
    server.use(
      http.get(apiUrl('/api/v1/datasets'), () =>
        HttpResponse.json({ code: 101, message: 'boom', data: false }),
      ),
    )
    await expect(createClient().fetchQuery(datasetsListQueryOptions())).rejects.toThrow('boom')

    server.use(
      http.get(apiUrl('/api/v1/datasets'), () =>
        HttpResponse.json({ code: 101, message: 'padł', data: false }, { status: 500 }),
      ),
    )
    await expect(createClient().fetchQuery(datasetsListQueryOptions())).rejects.toThrow('padł')
  })
})

describe('datasetQueryOptions', () => {
  it('pobiera szczegół datasetu po id', async () => {
    const detail = fixtureDatasetDetail({ id: 'ds-7', name: 'Gamma' })
    let path = ''
    server.use(
      http.get(apiUrl('/api/v1/datasets/:datasetId'), ({ request }) => {
        path = new URL(request.url).pathname
        return HttpResponse.json({ code: 0, message: 'success', data: detail })
      }),
    )

    const dataset = await createClient().fetchQuery(datasetQueryOptions('ds-7'))

    expect(dataset).toEqual(detail)
    expect(path).toBe('/api/v1/datasets/ds-7')
    expect(datasetQueryOptions('ds-7').queryKey).toEqual(datasetKeys.detail('ds-7'))
  })
})

describe('useCreateDataset', () => {
  it('wysyła POST {name, embedding_model, chunk_method} i unieważnia datasetKeys.all', async () => {
    let body: unknown = null
    server.use(
      http.post(apiUrl('/api/v1/datasets'), async ({ request }) => {
        body = await request.json()
        return HttpResponse.json({ code: 0, message: 'success', data: { id: 'ds-2' } })
      }),
    )
    const client = createClient()
    client.setQueryData(datasetKeys.list(), [DATASET])
    client.setQueryData(datasetKeys.detail('ds-1'), DATASET)
    const { result } = renderHook(() => useCreateDataset(), { wrapper: wrapperFor(client) })

    let created: unknown
    await act(async () => {
      created = await result.current.mutateAsync({
        name: 'Nowy',
        embeddingModel: 'model-embd',
        chunkMethod: 'naive',
      })
    })

    expect(body).toEqual({ name: 'Nowy', embedding_model: 'model-embd', chunk_method: 'naive' })
    expect(created).toEqual({ id: 'ds-2' })
    expect(client.getQueryState(datasetKeys.list())?.isInvalidated).toBe(true)
    expect(client.getQueryState(datasetKeys.detail('ds-1'))?.isInvalidated).toBe(true)
  })
})

describe('useUpdateDataset', () => {
  it('wysyła PUT na id datasetu, zapisuje odpowiedź w cache szczegółu i unieważnia datasetKeys.all', async () => {
    let body: unknown = null
    let path = ''
    // Odpowiedź PUT różna od stanu sprzed zapisu — cache ma dostać dokładnie zwrócony obiekt (T10).
    const updated = { ...DATASET, name: 'Beta', parser_config: { pages: [[2, 3]] } }
    server.use(
      http.put(apiUrl('/api/v1/datasets/:datasetId'), async ({ request }) => {
        body = await request.json()
        path = new URL(request.url).pathname
        return HttpResponse.json({ code: 0, message: 'success', data: updated })
      }),
    )
    const client = createClient()
    client.setQueryData(datasetKeys.detail('ds-1'), DATASET)
    client.setQueryData(datasetKeys.logs('ds-1', {}), { logs: [], total: 0 })
    const { result } = renderHook(() => useUpdateDataset('ds-1'), { wrapper: wrapperFor(client) })

    await act(async () => {
      await result.current.mutateAsync({ name: 'Beta' })
    })

    expect(path).toBe('/api/v1/datasets/ds-1')
    expect(body).toEqual({ name: 'Beta' })
    expect(client.getQueryData(datasetKeys.detail('ds-1'))).toEqual(updated)
    expect(client.getQueryState(datasetKeys.detail('ds-1'))?.isInvalidated).toBe(true)
    expect(client.getQueryState(datasetKeys.logs('ds-1', {}))?.isInvalidated).toBe(true)
  })

  it('handler MSW zapisuje ciało PUT i scala je ze swoim magazynem', async () => {
    const bodies: Record<string, unknown>[] = []
    server.use(...datasetHandlers([DATASET], { onUpdate: (body) => bodies.push(body) }))
    const patch = { chunk_method: 'qa', parser_config: { chunk_token_num: 256 } }
    const client = createClient()
    const { result } = renderHook(() => useUpdateDataset('ds-1'), { wrapper: wrapperFor(client) })

    await act(async () => {
      await result.current.mutateAsync(patch)
    })

    expect(bodies).toEqual([patch])
    const dataset = await client.fetchQuery(datasetQueryOptions('ds-1'))
    expect(dataset).toMatchObject({ id: 'ds-1', name: 'Alfa', chunk_method: 'qa' })
    expect(dataset.parser_config).toEqual({ chunk_token_num: 256 })
  })
})

describe('useDeleteDatasets', () => {
  it('wysyła DELETE {ids} i unieważnia datasetKeys.all', async () => {
    let body: unknown = null
    server.use(
      http.delete(apiUrl('/api/v1/datasets'), async ({ request }) => {
        body = await request.json()
        return HttpResponse.json({ code: 0, message: 'success', data: { success_count: 1 } })
      }),
    )
    const client = createClient()
    client.setQueryData(datasetKeys.list(), [DATASET])
    const { result } = renderHook(() => useDeleteDatasets(), { wrapper: wrapperFor(client) })

    let deleted: unknown
    await act(async () => {
      deleted = await result.current.mutateAsync(['ds-1'])
    })

    expect(body).toEqual({ ids: ['ds-1'] })
    expect(deleted).toEqual({ success_count: 1 })
    expect(client.getQueryState(datasetKeys.list())?.isInvalidated).toBe(true)
  })
})

describe('ingestionSummaryQueryOptions', () => {
  it('pobiera podsumowanie ingestii datasetu', async () => {
    const summary = fixtureIngestionSummary({ doc_num: 3 })
    let path = ''
    server.use(
      http.get(apiUrl('/api/v1/datasets/:datasetId/ingestions/summary'), ({ request }) => {
        path = new URL(request.url).pathname
        return HttpResponse.json({ code: 0, message: 'success', data: summary })
      }),
    )

    const result = await createClient().fetchQuery(ingestionSummaryQueryOptions('ds-1'))

    expect(result).toEqual(summary)
    expect(path).toBe('/api/v1/datasets/ds-1/ingestions/summary')
    expect(ingestionSummaryQueryOptions('ds-1').queryKey).toEqual(datasetKeys.summary('ds-1'))
  })
})

describe('ingestionLogsQueryOptions', () => {
  it('wysyła stronę, sortowanie, log_type=file i filtr statusu jako operation_status', async () => {
    const seen: URL[] = []
    const log = fixtureIngestionLog({ id: 'log-3', operation_status: '3' })
    server.use(
      http.get(apiUrl('/api/v1/datasets/:datasetId/ingestions'), ({ request }) => {
        seen.push(new URL(request.url))
        return HttpResponse.json({ code: 0, message: 'success', data: { logs: [log], total: 1 } })
      }),
    )

    const client = createClient()

    const result = await client.fetchQuery(
      ingestionLogsQueryOptions('ds-1', { status: 3, page: 2, pageSize: 25 }),
    )
    await client.fetchQuery(ingestionLogsQueryOptions('ds-1', {}))

    expect(result).toEqual({ logs: [log], total: 1 })
    const params = seen[0]?.searchParams
    expect(params?.get('log_type')).toBe('file')
    expect(params?.get('page')).toBe('2')
    expect(params?.get('page_size')).toBe('25')
    expect(params?.get('orderby')).toBe('create_time')
    expect(params?.get('desc')).toBe('true')
    expect(params?.getAll('operation_status')).toEqual(['3'])
    expect(seen[1]?.searchParams.get('operation_status')).toBeNull()
    expect(seen[1]?.searchParams.get('log_type')).toBe('file')
    expect(ingestionLogsQueryOptions('ds-1', { status: 3 }).queryKey).toEqual(
      datasetKeys.logs('ds-1', { status: 3 }),
    )
    expect(datasetKeys.logs('ds-1')).toEqual(['datasets', 'detail', 'ds-1', 'logs', {}])
  })

  it('handler MSW zawęża listę do żądanego statusu', async () => {
    const done = fixtureIngestionLog({ id: 'log-done', operation_status: '3' })
    const failed = fixtureIngestionLog({ id: 'log-fail', operation_status: '4' })
    server.use(...datasetHandlers([DATASET], { logs: [done, failed] }))

    const all = await createClient().fetchQuery(ingestionLogsQueryOptions('ds-1', {}))
    const failedOnly = await createClient().fetchQuery(
      ingestionLogsQueryOptions('ds-1', { status: 4 }),
    )

    expect(all.logs.map((log) => log.id)).toEqual(['log-done', 'log-fail'])
    expect(all.total).toBe(2)
    expect(failedOnly).toEqual({ logs: [failed], total: 1 })
  })
})

describe('ingestionLogQueryOptions', () => {
  it('pobiera pojedynczy log ingestii', async () => {
    const log = fixtureIngestionLog({ id: 'log-2', progress_msg: 'Trwa parsowanie' })
    let path = ''
    server.use(
      http.get(apiUrl('/api/v1/datasets/:datasetId/ingestions/:logId'), ({ request }) => {
        path = new URL(request.url).pathname
        return HttpResponse.json({ code: 0, message: 'success', data: log })
      }),
    )

    const result = await createClient().fetchQuery(ingestionLogQueryOptions('ds-1', 'log-2'))

    expect(result).toEqual(log)
    expect(path).toBe('/api/v1/datasets/ds-1/ingestions/log-2')
    expect(ingestionLogQueryOptions('ds-1', 'log-2').queryKey).toEqual(
      datasetKeys.log('ds-1', 'log-2'),
    )
  })
})
