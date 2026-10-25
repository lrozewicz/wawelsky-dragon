import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, renderHook, waitFor } from '@testing-library/react'
import { HttpResponse, http } from 'msw'
import type { ReactNode } from 'react'
import { afterEach, describe, expect, it } from 'vitest'

import {
  apiUrl,
  fixtureRetrievalChunk,
  fixtureModel,
  modelsHandlers,
  retrievalHandlers,
} from '../../../test/msw/handlers'
import { server } from '../../../test/msw/server'

import { buildRetrievalBody, useRerankOptions, useRetrieval } from './queries'
import type { RetrievalParams } from './queries'
import { DEFAULT_SETTINGS } from './schema'

afterEach(cleanup)

function createClient(): QueryClient {
  return new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } })
}

function wrapperFor(client: QueryClient) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>
  }
}

const BASE: RetrievalParams = {
  datasetId: 'ds-1',
  question: 'co to jest RAG?',
  settings: DEFAULT_SETTINGS,
  page: 1,
}

/** Filtry metadanych dla testów ciała żądania (SC-E6-1b-06). */
const MANUAL_EMPTY = {
  ...DEFAULT_SETTINGS.metaDataFilter,
  method: 'manual' as const,
  manual: [],
}
const MANUAL_TYP_RAPORT = {
  ...DEFAULT_SETTINGS.metaDataFilter,
  method: 'manual' as const,
  manual: [{ key: 'typ', op: '=' as const, value: 'raport' }],
}

/** Klucze pomijane w ciele, gdy nie niosą wartości (K4: bez jawnych `null`). */
const OMITTED_KEYS = [
  'document_ids',
  'doc_ids',
  'size',
  'rerank_id',
  'cross_languages',
  'metadata_condition',
  'meta_data_filter',
] as const

describe('buildRetrievalBody', () => {
  it('mapuje ustawienia na ciało żądania (page_size = topN, highlight, dataset_ids)', () => {
    const body = buildRetrievalBody(BASE)

    expect(body).toMatchObject({
      question: 'co to jest RAG?',
      dataset_ids: ['ds-1'],
      page: 1,
      page_size: 10,
      similarity_threshold: 0.2,
      vector_similarity_weight: 0.3,
      highlight: true,
      keyword: false,
    })
  })

  it('dla ustawień domyślnych i bez documentIds nie ma kluczy z pustymi wartościami', () => {
    const body = buildRetrievalBody(BASE) as Record<string, unknown>

    for (const key of OMITTED_KEYS) {
      expect(key in body, key).toBe(false)
    }
  })

  it('nie wysyła knn_top_k: null — backend testuje `"knn_top_k" in body` i robi int(None) (DEC-151)', () => {
    const body = buildRetrievalBody(BASE)

    expect(body.knn_top_k).toBe(1024)
    expect(body.knn_top_k).toBe(body.top_k)
    expect(body).not.toMatchObject({ knn_top_k: null })
  })

  it('wysyła rerank_id tylko dla wybranego modelu', () => {
    expect('rerank_id' in buildRetrievalBody(BASE)).toBe(false)
    expect(
      buildRetrievalBody({ ...BASE, settings: { ...DEFAULT_SETTINGS, rerankId: 'rerank-x' } })
        .rerank_id,
    ).toBe('rerank-x')
  })

  it('document_ids tylko dla niepustej listy dokumentów', () => {
    expect('document_ids' in buildRetrievalBody({ ...BASE, documentIds: [] })).toBe(false)
    expect(buildRetrievalBody({ ...BASE, documentIds: ['doc-1', 'doc-2'] }).document_ids).toEqual([
      'doc-1',
      'doc-2',
    ])
  })

  it('cross_languages tylko dla niepustej listy języków', () => {
    expect('cross_languages' in buildRetrievalBody(BASE)).toBe(false)
    expect(
      buildRetrievalBody({
        ...BASE,
        settings: { ...DEFAULT_SETTINGS, crossLanguages: ['German'] },
      }).cross_languages,
    ).toEqual(['German'])
  })

  it('meta_data_filter tylko, gdy filtr realnie zawęża (SC-E6-1b-06)', () => {
    expect('meta_data_filter' in buildRetrievalBody(BASE)).toBe(false)
    // Ręczny bez warunków niczego nie filtruje — pole pominięte.
    expect(
      'meta_data_filter' in
        buildRetrievalBody({
          ...BASE,
          settings: { ...DEFAULT_SETTINGS, metaDataFilter: MANUAL_EMPTY },
        }),
    ).toBe(false)
    // Ręczny z warunkiem: kształt drutu kontraktu §1.
    expect(
      buildRetrievalBody({
        ...BASE,
        settings: { ...DEFAULT_SETTINGS, metaDataFilter: MANUAL_TYP_RAPORT },
      }).meta_data_filter,
    ).toEqual({
      method: 'manual',
      logic: 'and',
      manual: [{ key: 'typ', op: '=', value: 'raport' }],
    })
  })
})

describe('useRetrieval', () => {
  it('wysyła ciało na serwer i zwraca wynik', async () => {
    const bodies: Record<string, unknown>[] = []
    server.use(
      ...retrievalHandlers({
        chunks: [fixtureRetrievalChunk({ id: 'chunk-9', content: 'Alfa' })],
        onRequest: (body) => bodies.push(body),
      }),
    )

    const { result } = renderHook(() => useRetrieval(), { wrapper: wrapperFor(createClient()) })

    result.current.mutate(BASE)
    await waitFor(() => expect(result.current.isSuccess).toBe(true))

    expect(bodies[0]).toMatchObject({ question: 'co to jest RAG?', dataset_ids: ['ds-1'] })
    expect(bodies[0]).toMatchObject({ knn_top_k: 1024 })
    expect(bodies[0] !== undefined && 'cross_languages' in bodies[0]).toBe(false)
    expect(result.current.data?.total).toBe(1)
    expect(result.current.data?.chunks[0]?.content).toBe('Alfa')
  })

  it('kończy się błędem, gdy serwer zwraca 500', async () => {
    server.use(
      http.post(apiUrl('/api/v1/retrieval'), () =>
        HttpResponse.json({ code: 1, message: 'boom' }, { status: 500 }),
      ),
    )

    const { result } = renderHook(() => useRetrieval(), { wrapper: wrapperFor(createClient()) })

    result.current.mutate(BASE)

    await waitFor(() => expect(result.current.isError).toBe(true))
  })
})

describe('useRerankOptions', () => {
  it('zwraca unikalne nazwy modeli rerank', async () => {
    server.use(
      ...modelsHandlers([
        fixtureModel({ name: 'chat-x', model_type: ['chat'] }),
        fixtureModel({ name: 'rerank-b', model_type: ['rerank'] }),
        fixtureModel({ name: 'rerank-a', model_type: ['rerank'] }),
        fixtureModel({ name: 'rerank-a', model_type: ['rerank', 'chat'] }),
      ]),
    )

    const { result } = renderHook(() => useRerankOptions(), { wrapper: wrapperFor(createClient()) })

    await waitFor(() => expect(result.current).toHaveLength(2))
    expect(result.current).toEqual(['rerank-b', 'rerank-a'])
  })
})
