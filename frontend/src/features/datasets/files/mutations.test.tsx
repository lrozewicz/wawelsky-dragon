import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, cleanup, renderHook, waitFor } from '@testing-library/react'
import { HttpResponse, http } from 'msw'
import type { ReactNode } from 'react'
import { afterEach, describe, expect, it } from 'vitest'

import {
  apiUrl,
  documentsHandlers,
  fixtureDatasetDetail,
  fixtureDocument,
} from '../../../test/msw/handlers'
import { server } from '../../../test/msw/server'
import { datasetKeys } from '../queries'

import {
  useBatchUpdateStatus,
  useDeleteDocuments,
  useParseDocuments,
  useStopDocuments,
  useToggleDocument,
  useUpdateDocument,
} from './mutations'
import {
  DEFAULT_DOCUMENTS_QUERY,
  documentKeys,
  documentsListQueryOptions,
  type DocumentRow,
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

const listKey = documentKeys.list('ds-1', DEFAULT_DOCUMENTS_QUERY)

function seedList(client: QueryClient, docs: DocumentRow[]): void {
  client.setQueryData(listKey, { docs, total: docs.length })
  client.setQueryData(datasetKeys.detail('ds-1'), fixtureDatasetDetail({ id: 'ds-1' }))
}

function cachedStatus(client: QueryClient, id: string): DocumentRow['status'] | undefined {
  const data = client.getQueryData<{ docs: DocumentRow[] }>(listKey)
  return data?.docs.find((doc) => doc.id === id)?.status
}

function isInvalidated(client: QueryClient, key: readonly unknown[]): boolean {
  return client.getQueryState(key)?.isInvalidated === true
}

describe('mutacje dokumentów', () => {
  it('wysyła ciała żądań zgodne z trasami v0.27', async () => {
    const calls: { kind: string; body: unknown }[] = []
    server.use(
      ...documentsHandlers(
        [fixtureDocument({ id: 'doc-1' }), fixtureDocument({ id: 'doc-2', name: 'b.docx' })],
        { onRequest: (kind, body) => calls.push({ kind, body }) },
      ),
    )
    const client = createClient()
    const { result } = renderHook(
      () => ({
        update: useUpdateDocument('ds-1'),
        toggle: useToggleDocument('ds-1'),
        remove: useDeleteDocuments('ds-1'),
        parse: useParseDocuments('ds-1'),
        stop: useStopDocuments('ds-1'),
        batch: useBatchUpdateStatus('ds-1'),
      }),
      { wrapper: wrapperFor(client) },
    )

    await act(async () => {
      await result.current.update.mutateAsync({ id: 'doc-1', patch: { name: 'Nowa.pdf' } })
      await result.current.toggle.mutateAsync({ id: 'doc-1', enabled: false })
      await result.current.remove.mutateAsync({ ids: ['doc-2'] })
      await result.current.parse.mutateAsync({ ids: ['doc-1'] })
      await result.current.stop.mutateAsync({ ids: ['doc-1'] })
      await result.current.batch.mutateAsync({ ids: ['doc-1', 'doc-2'], enabled: true })
    })

    expect(calls).toEqual([
      { kind: 'update', body: { name: 'Nowa.pdf' } },
      { kind: 'update', body: { enabled: 0 } },
      { kind: 'delete', body: { ids: ['doc-2'] } },
      { kind: 'parse', body: { document_ids: ['doc-1'] } },
      { kind: 'stop', body: { document_ids: ['doc-1'] } },
      { kind: 'batch', body: { doc_ids: ['doc-1', 'doc-2'], status: '1' } },
    ])
  })

  it('zmienia metodę chunkowania i włączenie osobnymi łatkami PATCH', async () => {
    const patches: unknown[] = []
    server.use(
      ...documentsHandlers([fixtureDocument({ id: 'doc-1' })], {
        onRequest: (kind, body) => {
          if (kind === 'update') patches.push(body)
        },
      }),
    )
    const client = createClient()
    const { result } = renderHook(
      () => ({ update: useUpdateDocument('ds-1'), toggle: useToggleDocument('ds-1') }),
      { wrapper: wrapperFor(client) },
    )

    await act(async () => {
      await result.current.update.mutateAsync({ id: 'doc-1', patch: { chunk_method: 'qa' } })
      await result.current.toggle.mutateAsync({ id: 'doc-1', enabled: true })
    })

    expect(patches).toEqual([{ chunk_method: 'qa' }, { enabled: 1 }])
  })

  it('pokazuje optymistyczną zmianę statusu przed odpowiedzią i wycofuje ją po błędzie', async () => {
    let release: () => void = () => {}
    const gate = new Promise<void>((resolve) => {
      release = resolve
    })
    server.use(
      http.patch(apiUrl('/api/v1/datasets/:datasetId/documents/:documentId'), async () => {
        await gate
        return HttpResponse.json({ code: 102, message: 'Nie znaleziono dokumentu', data: null })
      }),
    )
    const client = createClient()
    seedList(client, [fixtureDocument({ id: 'doc-1', status: '1' })])
    const { result } = renderHook(() => useToggleDocument('ds-1'), { wrapper: wrapperFor(client) })

    act(() => {
      result.current.mutate({ id: 'doc-1', enabled: false })
    })

    // Optymistyczna zmiana jest w cache, zanim handler MSW zwolni odpowiedź.
    await waitFor(() => {
      expect(cachedStatus(client, 'doc-1')).toBe('0')
    })

    release()

    await waitFor(() => {
      expect(cachedStatus(client, 'doc-1')).toBe('1')
    })
  })

  it('po sukcesie przełączenia unieważnia listę dokumentów i licznik nagłówka', async () => {
    server.use(...documentsHandlers([fixtureDocument({ id: 'doc-1' })]))
    const client = createClient()
    seedList(client, [fixtureDocument({ id: 'doc-1' })])
    const { result } = renderHook(() => useToggleDocument('ds-1'), { wrapper: wrapperFor(client) })

    await act(async () => {
      await result.current.mutateAsync({ id: 'doc-1', enabled: false })
    })

    expect(isInvalidated(client, listKey)).toBe(true)
    expect(isInvalidated(client, datasetKeys.detail('ds-1'))).toBe(true)
  })

  it('po usunięciu i akcji zbiorczej unieważnia listę dokumentów i licznik nagłówka', async () => {
    server.use(
      ...documentsHandlers([
        fixtureDocument({ id: 'doc-1' }),
        fixtureDocument({ id: 'doc-2', name: 'b.docx' }),
      ]),
    )
    const client = createClient()
    seedList(client, [fixtureDocument({ id: 'doc-1' })])
    const { result } = renderHook(
      () => ({ remove: useDeleteDocuments('ds-1'), batch: useBatchUpdateStatus('ds-1') }),
      { wrapper: wrapperFor(client) },
    )

    await act(async () => {
      await result.current.remove.mutateAsync({ ids: ['doc-2'] })
    })
    expect(isInvalidated(client, listKey)).toBe(true)
    expect(isInvalidated(client, datasetKeys.detail('ds-1'))).toBe(true)

    client.clear()
    seedList(client, [fixtureDocument({ id: 'doc-1' })])
    await act(async () => {
      await result.current.batch.mutateAsync({ ids: ['doc-1'], enabled: false })
    })
    expect(isInvalidated(client, listKey)).toBe(true)
    expect(isInvalidated(client, datasetKeys.detail('ds-1'))).toBe(true)
  })

  it('parse unieważnia tylko listę dokumentów, a kolejne pobranie widzi stan serwera', async () => {
    server.use(...documentsHandlers([fixtureDocument({ id: 'doc-1', run: 'UNSTART' })]))
    const client = createClient()
    seedList(client, [fixtureDocument({ id: 'doc-1', run: 'UNSTART' })])
    const { result } = renderHook(() => useParseDocuments('ds-1'), { wrapper: wrapperFor(client) })

    await act(async () => {
      await result.current.mutateAsync({ ids: ['doc-1'] })
    })

    expect(isInvalidated(client, listKey)).toBe(true)
    expect(isInvalidated(client, datasetKeys.detail('ds-1'))).toBe(false)

    const refreshed = await client.fetchQuery(
      documentsListQueryOptions('ds-1', DEFAULT_DOCUMENTS_QUERY),
    )
    expect(refreshed.docs[0]?.run).toBe('SCHEDULE')
  })

  it('stop unieważnia tylko listę dokumentów', async () => {
    server.use(...documentsHandlers([fixtureDocument({ id: 'doc-1', run: 'RUNNING' })]))
    const client = createClient()
    seedList(client, [fixtureDocument({ id: 'doc-1', run: 'RUNNING' })])
    const { result } = renderHook(() => useStopDocuments('ds-1'), { wrapper: wrapperFor(client) })

    await act(async () => {
      await result.current.mutateAsync({ ids: ['doc-1'] })
    })

    expect(isInvalidated(client, listKey)).toBe(true)
    expect(isInvalidated(client, datasetKeys.detail('ds-1'))).toBe(false)
  })
})
