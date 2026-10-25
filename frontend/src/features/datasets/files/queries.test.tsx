import { QueryClient } from '@tanstack/react-query'
import { describe, expect, it } from 'vitest'

import { documentsHandlers, fixtureDocument } from '../../../test/msw/handlers'
import { server } from '../../../test/msw/server'

import {
  DEFAULT_DOCUMENTS_QUERY,
  documentKeys,
  documentsListQueryOptions,
  POLL_INTERVAL_MS,
  type DocumentRow,
  type DocumentsQuery,
} from './queries'

function createClient(): QueryClient {
  return new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } })
}

function captureListUrls(docs: DocumentRow[]): URL[] {
  const seen: URL[] = []
  server.use(
    ...documentsHandlers(docs, {
      onRequest: (kind, _body, url) => {
        if (kind === 'list') seen.push(url)
      },
    }),
  )
  return seen
}

describe('documentsListQueryOptions', () => {
  it('wysyła stronę, sortowanie i niepuste filtry do zapytania', async () => {
    const seen = captureListUrls([fixtureDocument()])
    const client = createClient()
    const conditionalParam =
      '{"logic":"and","conditions":[{"name":"typ","comparison_operator":"=","value":"raport"}]}'
    const query: DocumentsQuery = {
      page: 2,
      pageSize: 25,
      orderby: 'update_time',
      desc: false,
      keywords: 'raport',
      suffix: ['pdf'],
      run: ['1'],
      metadataCondition: conditionalParam,
    }

    await client.fetchQuery(documentsListQueryOptions('ds-1', query))
    await client.fetchQuery(documentsListQueryOptions('ds-1', DEFAULT_DOCUMENTS_QUERY))

    const params = seen[0]?.searchParams
    expect(params?.get('page')).toBe('2')
    expect(params?.get('page_size')).toBe('25')
    expect(params?.get('orderby')).toBe('update_time')
    expect(params?.get('desc')).toBe('false')
    expect(params?.get('keywords')).toBe('raport')
    expect(params?.getAll('run')).toEqual(['1'])
    expect(params?.getAll('suffix')).toEqual(['pdf'])
    // Niepusty filtr metadanych jedzie jako `?metadata_condition=` (K11 §10f).
    expect(params?.get('metadata_condition')).toBe(conditionalParam)

    // Puste `keywords`/`suffix`/`run`/`metadataCondition` nie trafiają do adresu.
    const empty = seen[1]?.searchParams
    expect(empty?.get('keywords')).toBeNull()
    expect(empty?.getAll('run')).toEqual([])
    expect(empty?.getAll('suffix')).toEqual([])
    expect(empty?.get('metadata_condition')).toBeNull()
  })

  it('zwraca dokumenty i liczbę łączną, klucz pod prefiksem documents', async () => {
    server.use(
      ...documentsHandlers([
        fixtureDocument({ id: 'doc-1' }),
        fixtureDocument({ id: 'doc-2', name: 'b.docx', suffix: 'docx' }),
      ]),
    )

    const result = await createClient().fetchQuery(
      documentsListQueryOptions('ds-1', DEFAULT_DOCUMENTS_QUERY),
    )

    expect(result.docs.map((doc) => doc.id)).toEqual(['doc-1', 'doc-2'])
    expect(result.total).toBe(2)
    expect(documentsListQueryOptions('ds-1', DEFAULT_DOCUMENTS_QUERY).queryKey).toEqual(
      documentKeys.list('ds-1', DEFAULT_DOCUMENTS_QUERY),
    )
  })

  it('refetchInterval odpytuje co 3 s w trakcie parsowania i nie odpytuje dla DONE', () => {
    const options = documentsListQueryOptions('ds-1', DEFAULT_DOCUMENTS_QUERY)

    expect(options.placeholderData).toBeDefined()
    const decide = options.refetchInterval as unknown as (query: {
      state: { data?: { docs: DocumentRow[] } }
    }) => number | false

    expect(decide({ state: { data: { docs: [fixtureDocument({ run: 'RUNNING' })] } } })).toBe(
      POLL_INTERVAL_MS,
    )
    expect(
      decide({ state: { data: { docs: [fixtureDocument({ run: 'DONE', progress: 1 })] } } }),
    ).toBe(false)
    expect(decide({ state: {} })).toBe(false)
  })

  it('klucze dokumentów siedzą pod prefiksem [datasets, detail, id, documents]', () => {
    expect(documentKeys.all('ds-1')).toEqual(['datasets', 'detail', 'ds-1', 'documents'])
    expect(documentKeys.list('ds-1', DEFAULT_DOCUMENTS_QUERY).slice(0, 4)).toEqual([
      'datasets',
      'detail',
      'ds-1',
      'documents',
    ])
  })
})
