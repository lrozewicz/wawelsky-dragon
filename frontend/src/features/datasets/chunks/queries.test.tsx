import { QueryClient } from '@tanstack/react-query'
import { describe, expect, it } from 'vitest'

import { chunksHandlers, fixtureChunk } from '../../../test/msw/handlers'
import { server } from '../../../test/msw/server'

import {
  CHUNKS_PAGE_SIZE,
  chunkKeys,
  chunksListQueryOptions,
  type Chunk,
  type ChunksQuery,
} from './queries'

function createClient(): QueryClient {
  return new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } })
}

/** Adresy listy widziane przez handler (kolejność wywołań). */
function captureListUrls(chunks: Chunk[]): string[] {
  const seen: string[] = []
  server.use(
    ...chunksHandlers(chunks, {
      onRequest: (req) => {
        if (req.method === 'GET') seen.push(req.url)
      },
    }),
  )
  return seen
}

const baseQuery: ChunksQuery = {
  page: 1,
  pageSize: CHUNKS_PAGE_SIZE,
  keywords: '',
  available: 'all',
}

describe('chunksListQueryOptions', () => {
  it('wysyła stronę, rozmiar i słowa kluczowe, a puste pomija', async () => {
    const seen = captureListUrls([fixtureChunk()])
    const client = createClient()

    await client.fetchQuery(
      chunksListQueryOptions('ds-1', 'doc-1', {
        page: 2,
        pageSize: 30,
        keywords: 'Treść',
        available: 'all',
      }),
    )
    await client.fetchQuery(chunksListQueryOptions('ds-1', 'doc-1', baseQuery))

    const filled = new URL(seen[0] ?? '')
    expect(filled.pathname).toBe('/api/v1/datasets/ds-1/documents/doc-1/chunks')
    expect(filled.searchParams.get('page')).toBe('2')
    expect(filled.searchParams.get('page_size')).toBe('30')
    expect(filled.searchParams.get('keywords')).toBe('Treść')

    // Pusty `keywords` nie trafia do adresu.
    const empty = new URL(seen[1] ?? '')
    expect(empty.searchParams.get('keywords')).toBeNull()
  })

  it('mapuje filtr na `available`: enabled → true, disabled → false, all → brak', async () => {
    const seen = captureListUrls([fixtureChunk()])
    const client = createClient()

    await client.fetchQuery(
      chunksListQueryOptions('ds-1', 'doc-1', { ...baseQuery, available: 'enabled' }),
    )
    await client.fetchQuery(
      chunksListQueryOptions('ds-1', 'doc-1', { ...baseQuery, available: 'disabled' }),
    )
    await client.fetchQuery(
      chunksListQueryOptions('ds-1', 'doc-1', { ...baseQuery, available: 'all' }),
    )

    const [enabled, disabled, all] = seen.map((url) => new URL(url))
    expect(enabled?.searchParams.get('available')).toBe('true')
    expect(disabled?.searchParams.get('available')).toBe('false')
    expect(all?.searchParams.get('available')).toBeNull()
  })

  it('handler filtruje wg `available` i liczy `total` po filtrze', async () => {
    server.use(
      ...chunksHandlers([
        fixtureChunk({ id: 'c1', available: true }),
        fixtureChunk({ id: 'c2', available: false }),
        fixtureChunk({ id: 'c3', available: false }),
      ]),
    )
    const client = createClient()

    const disabled = await client.fetchQuery(
      chunksListQueryOptions('ds-1', 'doc-1', { ...baseQuery, available: 'disabled' }),
    )
    expect(disabled.chunks.map((chunk) => chunk.id)).toEqual(['c2', 'c3'])
    expect(disabled.total).toBe(2)

    const enabled = await client.fetchQuery(
      chunksListQueryOptions('ds-1', 'doc-1', { ...baseQuery, available: 'enabled' }),
    )
    expect(enabled.chunks.map((chunk) => chunk.id)).toEqual(['c1'])
    expect(enabled.total).toBe(1)
  })

  it('filtruje po treści chunku po stronie handlera', async () => {
    server.use(
      ...chunksHandlers([
        fixtureChunk({ id: 'c1', content: 'Treść chunku' }),
        fixtureChunk({ id: 'c2', content: 'Inny fragment' }),
      ]),
    )

    const result = await createClient().fetchQuery(
      chunksListQueryOptions('ds-1', 'doc-1', { ...baseQuery, keywords: 'inny' }),
    )

    expect(result.chunks.map((chunk) => chunk.id)).toEqual(['c2'])
    expect(result.total).toBe(1)
  })

  it('zwraca chunki, liczbę łączną i dokument, klucz pod prefiksem chunks', async () => {
    server.use(
      ...chunksHandlers([
        fixtureChunk({ id: 'c1' }),
        fixtureChunk({ id: 'c2', content: 'Inny fragment' }),
      ]),
    )

    const result = await createClient().fetchQuery(
      chunksListQueryOptions('ds-1', 'doc-1', baseQuery),
    )

    expect(result.chunks.map((chunk) => chunk.id)).toEqual(['c1', 'c2'])
    expect(result.total).toBe(2)
    expect(result.doc.id).toBe('doc-1')
    expect(result.doc.name).toBe('plik.pdf')
    expect(result.doc.chunk_count).toBe(2)
    expect(chunksListQueryOptions('ds-1', 'doc-1', baseQuery).queryKey).toEqual(
      chunkKeys.list('ds-1', 'doc-1', baseQuery),
    )
  })

  it('klucze chunków siedzą pod prefiksem [datasets, detail, id, chunks, doc]', () => {
    expect(chunkKeys.all('ds-1', 'doc-1')).toEqual([
      'datasets',
      'detail',
      'ds-1',
      'chunks',
      'doc-1',
    ])
    expect(chunkKeys.list('ds-1', 'doc-1', baseQuery).slice(0, 5)).toEqual([
      'datasets',
      'detail',
      'ds-1',
      'chunks',
      'doc-1',
    ])
  })
})
