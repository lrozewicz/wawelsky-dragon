import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, cleanup, renderHook, waitFor } from '@testing-library/react'
import { HttpResponse, http } from 'msw'
import type { ReactNode } from 'react'
import { afterEach, describe, expect, it } from 'vitest'

import {
  apiUrl,
  chunksHandlers,
  fixtureChunk,
  fixtureDatasetDetail,
  fixtureDocument,
} from '../../../test/msw/handlers'
import { server } from '../../../test/msw/server'
import { datasetKeys } from '../queries'
import { DEFAULT_DOCUMENTS_QUERY, documentKeys } from '../files/queries'

import { useCreateChunk, useDeleteChunks, useSwitchChunks, useUpdateChunk } from './mutations'
import { CHUNKS_PAGE_SIZE, chunkKeys, type Chunk, type ChunkDoc, type ChunksQuery } from './queries'

afterEach(cleanup)

function createClient(): QueryClient {
  return new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } })
}

function wrapperFor(client: QueryClient) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>
  }
}

const query: ChunksQuery = { page: 1, pageSize: CHUNKS_PAGE_SIZE, keywords: '', available: 'all' }
const listKey = chunkKeys.list('ds-1', 'doc-1', query)
const documentsListKey = documentKeys.list('ds-1', DEFAULT_DOCUMENTS_QUERY)

/** Zasiewa cache listą chunków, listą dokumentów i szczegółem datasetu (jak `chunksListQueryOptions`). */
function seedList(client: QueryClient, chunks: Chunk[]): void {
  const doc: ChunkDoc = { ...fixtureDocument({ id: 'doc-1' }), content_hash: '' }
  client.setQueryData(listKey, { chunks, total: chunks.length, doc })
  client.setQueryData(documentsListKey, { docs: [], total: 0 })
  client.setQueryData(datasetKeys.detail('ds-1'), fixtureDatasetDetail({ id: 'ds-1' }))
}

function cachedAvailable(client: QueryClient, id: string): boolean | undefined {
  const data = client.getQueryData<{ chunks: Chunk[] }>(listKey)
  return data?.chunks.find((chunk) => chunk.id === id)?.available
}

function isInvalidated(client: QueryClient, key: readonly unknown[]): boolean {
  return client.getQueryState(key)?.isInvalidated === true
}

describe('mutacje chunków', () => {
  it('wysyła ciała żądań zgodne z trasami v0.27', async () => {
    const calls: { method: string; url: string; body: unknown }[] = []
    server.use(
      ...chunksHandlers([fixtureChunk({ id: 'c1' }), fixtureChunk({ id: 'c2' })], {
        onRequest: (req) => calls.push(req),
      }),
    )
    const client = createClient()
    const { result } = renderHook(
      () => ({
        create: useCreateChunk('ds-1', 'doc-1'),
        update: useUpdateChunk('ds-1', 'doc-1'),
        toggle: useSwitchChunks('ds-1', 'doc-1'),
        remove: useDeleteChunks('ds-1', 'doc-1'),
      }),
      { wrapper: wrapperFor(client) },
    )

    await act(async () => {
      await result.current.create.mutateAsync({
        content: 'Nowy chunk',
        important_keywords: ['a'],
        questions: ['q?'],
      })
      await result.current.update.mutateAsync({ id: 'c1', patch: { important_keywords: ['a'] } })
      await result.current.toggle.mutateAsync({ ids: ['c1', 'c2'], available: false })
      await result.current.remove.mutateAsync({ ids: ['c1', 'c2'] })
    })

    const seen = calls.map((call) => ({
      method: call.method,
      path: new URL(call.url).pathname,
      body: call.body,
    }))
    expect(seen).toEqual([
      {
        method: 'POST',
        path: '/api/v1/datasets/ds-1/documents/doc-1/chunks',
        body: { content: 'Nowy chunk', important_keywords: ['a'], questions: ['q?'] },
      },
      {
        method: 'PATCH',
        path: '/api/v1/datasets/ds-1/documents/doc-1/chunks/c1',
        body: { important_keywords: ['a'] },
      },
      {
        method: 'PATCH',
        path: '/api/v1/datasets/ds-1/documents/doc-1/chunks',
        body: { chunk_ids: ['c1', 'c2'], available: false },
      },
      {
        method: 'DELETE',
        path: '/api/v1/datasets/ds-1/documents/doc-1/chunks',
        body: { chunk_ids: ['c1', 'c2'] },
      },
    ])
  })

  it('pokazuje optymistyczną zmianę available przed odpowiedzią i wycofuje ją po błędzie', async () => {
    let release: () => void = () => {}
    const gate = new Promise<void>((resolve) => {
      release = resolve
    })
    server.use(
      http.patch(apiUrl('/api/v1/datasets/:datasetId/documents/:documentId/chunks'), async () => {
        await gate
        return HttpResponse.json({ code: 102, message: 'Brak dostępu', data: null })
      }),
    )
    const client = createClient()
    seedList(client, [fixtureChunk({ id: 'c1', available: true })])
    const { result } = renderHook(() => useSwitchChunks('ds-1', 'doc-1'), {
      wrapper: wrapperFor(client),
    })

    act(() => {
      result.current.mutate({ ids: ['c1'], available: false })
    })

    // Optymistyczna zmiana jest w cache, zanim handler MSW zwolni odpowiedź.
    await waitFor(() => {
      expect(cachedAvailable(client, 'c1')).toBe(false)
    })

    release()

    await waitFor(() => {
      expect(cachedAvailable(client, 'c1')).toBe(true)
    })
  })

  it('po sukcesie przełączenia unieważnia chunki, dokumenty i szczegół datasetu', async () => {
    server.use(...chunksHandlers([fixtureChunk({ id: 'c1' })]))
    const client = createClient()
    seedList(client, [fixtureChunk({ id: 'c1' })])
    const { result } = renderHook(() => useSwitchChunks('ds-1', 'doc-1'), {
      wrapper: wrapperFor(client),
    })

    await act(async () => {
      await result.current.mutateAsync({ ids: ['c1'], available: false })
    })

    expect(isInvalidated(client, listKey)).toBe(true)
    expect(isInvalidated(client, documentsListKey)).toBe(true)
    expect(isInvalidated(client, datasetKeys.detail('ds-1'))).toBe(true)
  })
})
