import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, renderHook, waitFor } from '@testing-library/react'
import { HttpResponse, http } from 'msw'
import type { ReactNode } from 'react'
import { afterEach, describe, expect, it } from 'vitest'

import { apiUrl, fixtureRetrievalChunk, retrievalHandlers } from '../../../test/msw/handlers'
import { server } from '../../../test/msw/server'

import { buildHitsBody, useSearchHits } from './useSearchHits'
import type { SearchHitsParams } from './useSearchHits'

afterEach(cleanup)

function createClient(): QueryClient {
  return new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } })
}

function wrapperFor(client: QueryClient) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>
  }
}

const BASE: SearchHitsParams = {
  question: 'q',
  config: { kb_ids: ['a'] },
  page: 2,
  pageSize: 10,
  docIds: [],
}

describe('buildHitsBody', () => {
  it('mapuje config i stronę na ciało żądania (kontrakt §3, przykład 1)', () => {
    expect(buildHitsBody(BASE)).toEqual({
      question: 'q',
      dataset_ids: ['a'],
      page: 2,
      page_size: 10,
      similarity_threshold: 0.2,
      vector_similarity_weight: 0.3,
      highlight: true,
      top_k: 1024,
      knn_top_k: 1024,
      rerank_candidates_count: 64,
      keyword: false,
    })
  })

  it('dokłada doc_ids tylko z niepustą listą (kontrakt §3, przykład 2)', () => {
    const body = buildHitsBody({ ...BASE, docIds: ['d1'] })

    expect(body.doc_ids).toEqual(['d1'])
    expect(body).not.toHaveProperty('document_ids')
  })

  it('filtr ręczny bez warunków NIE idzie do /retrieval — spójnie z buildRetrievalBody (T6 d)', () => {
    // `search_config.meta_data_filter` po zapisie kreatora `{method:'manual', logic, manual:[]}`
    // niczego nie odfiltrowuje — pole pomijane jak przy „Wyłączony” (kontrakt WP E6-1b §1).
    expect(
      buildHitsBody({
        ...BASE,
        config: { kb_ids: ['a'], meta_data_filter: { method: 'manual', logic: 'and', manual: [] } },
      }),
    ).not.toHaveProperty('meta_data_filter')

    expect(
      buildHitsBody({
        ...BASE,
        config: {
          kb_ids: ['a'],
          meta_data_filter: {
            method: 'manual',
            logic: 'and',
            manual: [{ key: 'typ', op: '=', value: 'raport' }],
          },
        },
      }),
    ).toMatchObject({ meta_data_filter: { method: 'manual', manual: [{ key: 'typ' }] } })
  })

  it('dokłada rerank_id tylko gdy niepusty, a progi bierze z configu', () => {
    const body = buildHitsBody({
      ...BASE,
      config: { kb_ids: ['a'], similarity_threshold: 0.5, vector_similarity_weight: 0.7 },
    })
    expect(body.similarity_threshold).toBe(0.5)
    expect(body.vector_similarity_weight).toBe(0.7)
    expect(body).not.toHaveProperty('rerank_id')

    expect(
      buildHitsBody({ ...BASE, config: { kb_ids: ['a'], rerank_id: 'bge-rerank' } }),
    ).toMatchObject({
      rerank_id: 'bge-rerank',
    })
  })
})

describe('useSearchHits', () => {
  it('zwraca chunks, doc_aggs i total z odpowiedzi', async () => {
    server.use(...retrievalHandlers({ chunks: [fixtureRetrievalChunk()] }))
    const { result } = renderHook(() => useSearchHits({ ...BASE, page: 1 }), {
      wrapper: wrapperFor(createClient()),
    })

    await waitFor(() => expect(result.current.data?.total).toBe(1))
    expect(result.current.data?.chunks).toHaveLength(1)
    expect(result.current.data?.doc_aggs).toEqual([
      { doc_id: 'doc-1', doc_name: 'plik.pdf', count: 1 },
    ])
  })

  it('dla null nie wysyła żądania', async () => {
    let requests = 0
    server.use(
      http.post(apiUrl('/api/v1/retrieval'), () => {
        requests += 1
        return HttpResponse.json({
          code: 0,
          message: '',
          data: { chunks: [], doc_aggs: [], total: 0 },
        })
      }),
    )
    const { result } = renderHook(() => useSearchHits(null), {
      wrapper: wrapperFor(createClient()),
    })

    await new Promise((resolve) => setTimeout(resolve, 10))
    expect(requests).toBe(0)
    expect(result.current.isFetching).toBe(false)
    expect(result.current.data).toBeUndefined()
  })

  it('zmiana strony zachowuje poprzednie dane (keepPreviousData)', async () => {
    const gate: { release: null | (() => void) } = { release: null }
    server.use(
      http.post(apiUrl('/api/v1/retrieval'), async ({ request }) => {
        const body = (await request.json()) as { page: number }
        if (body.page === 2) {
          await new Promise<void>((resolve) => {
            gate.release = resolve
          })
        }
        return HttpResponse.json({
          code: 0,
          message: 'success',
          data: { chunks: [], doc_aggs: [], total: body.page },
        })
      }),
    )
    const { result, rerender } = renderHook(({ p }: { p: SearchHitsParams }) => useSearchHits(p), {
      initialProps: { p: { ...BASE, page: 1 } },
      wrapper: wrapperFor(createClient()),
    })
    await waitFor(() => expect(result.current.data?.total).toBe(1))

    rerender({ p: { ...BASE, page: 2 } })
    await waitFor(() => expect(gate.release).not.toBeNull())
    expect(result.current.data?.total).toBe(1)

    gate.release?.()
    await waitFor(() => expect(result.current.data?.total).toBe(2))
  })
})
