import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, cleanup, renderHook } from '@testing-library/react'
import { HttpResponse, http } from 'msw'
import type { ReactNode } from 'react'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import {
  SEARCH_TIMESTAMP,
  apiUrl,
  resetSearchesFixtures,
  searchFixtureApp,
} from '../../test/msw/handlers'
import { server } from '../../test/msw/server'

import {
  searchKeys,
  searchQueryOptions,
  searchesListQueryOptions,
  useCreateSearch,
  useDeleteSearch,
  useRenameSearch,
  useUpdateSearchConfig,
} from './queries'
import type { SearchListItem } from './queries'
import { toFormValues } from './settings/schema'

afterEach(cleanup)
// Magazyn MSW jest wspólny dla pliku — każdy test startuje od ziarna `searchFixtureApp`.
beforeEach(resetSearchesFixtures)

const LIST_ITEM: SearchListItem = {
  id: 'search-1',
  name: 'Alfa',
  description: null,
  avatar: null,
  created_by: 'user-1',
  tenant_id: 'tenant-1',
  create_time: SEARCH_TIMESTAMP,
  update_time: SEARCH_TIMESTAMP,
  nickname: 'recorder',
  status: '1',
  tenant_avatar: null,
}

function createClient(): QueryClient {
  return new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } })
}

/** Otoczka hooków mutacji — każdy test dostaje własny klient, żeby widzieć własne unieważnienia. */
function wrapperFor(client: QueryClient) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>
  }
}

describe('searchesListQueryOptions', () => {
  it('rozpakowuje data.search_apps i uderza w /api/v1/searches', async () => {
    let path = ''
    server.use(
      http.get(apiUrl('/api/v1/searches'), ({ request }) => {
        path = new URL(request.url).pathname
        return HttpResponse.json({
          code: 0,
          message: '',
          data: { search_apps: [LIST_ITEM], total: 1 },
        })
      }),
    )

    const items = await createClient().fetchQuery(searchesListQueryOptions())

    expect(items).toEqual([LIST_ITEM])
    expect(path).toBe('/api/v1/searches')
    expect(searchesListQueryOptions().queryKey).toEqual(searchKeys.list())
  })

  it('rzuca ApiError przy kopercie code ≠ 0', async () => {
    server.use(
      http.get(apiUrl('/api/v1/searches'), () =>
        HttpResponse.json({ code: 101, message: 'boom', data: false }),
      ),
    )

    await expect(createClient().fetchQuery(searchesListQueryOptions())).rejects.toThrow('boom')
  })
})

describe('searchQueryOptions', () => {
  it('pobiera szczegół wyszukiwarki po id', async () => {
    const detail = { ...searchFixtureApp, id: 'search-7', name: 'Gamma' }
    let path = ''
    server.use(
      http.get(`${apiUrl('/api/v1/searches')}/:searchId`, ({ request }) => {
        path = new URL(request.url).pathname
        return HttpResponse.json({ code: 0, message: '', data: detail })
      }),
    )

    const app = await createClient().fetchQuery(searchQueryOptions('search-7'))

    expect(app).toEqual(detail)
    expect(path).toBe('/api/v1/searches/search-7')
    expect(searchQueryOptions('search-7').queryKey).toEqual(searchKeys.detail('search-7'))
  })
})

describe('useCreateSearch', () => {
  it('wysyła POST z samą nazwą i unieważnia searchKeys.all', async () => {
    let body: unknown = null
    server.use(
      http.post(apiUrl('/api/v1/searches'), async ({ request }) => {
        body = await request.json()
        return HttpResponse.json({
          code: 0,
          message: '',
          data: { search_id: 'search-2' },
        })
      }),
    )
    const client = createClient()
    client.setQueryData(searchKeys.list(), [LIST_ITEM])
    const { result } = renderHook(() => useCreateSearch(), { wrapper: wrapperFor(client) })

    let created: unknown
    await act(async () => {
      created = await result.current.mutateAsync('Nowa')
    })

    expect(body).toEqual({ name: 'Nowa' })
    expect(created).toEqual({ search_id: 'search-2' })
    expect(client.getQueryState(searchKeys.list())?.isInvalidated).toBe(true)
  })
})

describe('useRenameSearch', () => {
  it('wysyła PUT z pełnym ciałem (name, description, search_config) i unieważnia searchKeys.all', async () => {
    let body: unknown = null
    let path = ''
    server.use(
      http.put(`${apiUrl('/api/v1/searches')}/:searchId`, async ({ request }) => {
        body = await request.json()
        path = new URL(request.url).pathname
        return HttpResponse.json({
          code: 0,
          message: '',
          data: { ...searchFixtureApp, name: 'X' },
        })
      }),
    )
    const client = createClient()
    client.setQueryData(searchKeys.list(), [LIST_ITEM])
    const { result } = renderHook(() => useRenameSearch(), { wrapper: wrapperFor(client) })

    await act(async () => {
      await result.current.mutateAsync({ id: 'search-1', name: 'X' })
    })

    expect(path).toBe('/api/v1/searches/search-1')
    expect(body).toEqual({
      name: 'X',
      description: 'Wyszukiwarka demonstracyjna',
      search_config: searchFixtureApp.search_config,
    })
    // Nieznany klucz `use_kg` przeżywa zmianę nazwy (backend zastępuje całe `search_config`).
    expect((body as { search_config: Record<string, unknown> }).search_config.use_kg).toBe(false)
    expect(client.getQueryState(searchKeys.list())?.isInvalidated).toBe(true)
  })

  it('handler odrzuca ciało bez search_config kodem 101', async () => {
    const response = await fetch(apiUrl('/api/v1/searches/search-1'), {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: 'X' }),
    })

    expect(await response.json()).toEqual({
      code: 101,
      message: 'required argument are missing: search_config; ',
      data: false,
    })
  })
})

describe('useDeleteSearch', () => {
  it('wysyła DELETE po id i unieważnia searchKeys.all', async () => {
    let path = ''
    server.use(
      http.delete(`${apiUrl('/api/v1/searches')}/:searchId`, ({ request }) => {
        path = new URL(request.url).pathname
        return HttpResponse.json({ code: 0, message: '', data: true })
      }),
    )
    const client = createClient()
    client.setQueryData(searchKeys.list(), [LIST_ITEM])
    const { result } = renderHook(() => useDeleteSearch(), { wrapper: wrapperFor(client) })

    let deleted: unknown
    await act(async () => {
      deleted = await result.current.mutateAsync('search-1')
    })

    expect(path).toBe('/api/v1/searches/search-1')
    expect(deleted).toBe(true)
    expect(client.getQueryState(searchKeys.list())?.isInvalidated).toBe(true)
  })
})

describe('useUpdateSearchConfig', () => {
  it('wysyła PUT z pełnym ciałem scalonym z bieżącym search_config', async () => {
    let body: unknown = null
    let path = ''
    server.use(
      http.put(`${apiUrl('/api/v1/searches')}/:searchId`, async ({ request }) => {
        body = await request.json()
        path = new URL(request.url).pathname
        return HttpResponse.json({ code: 0, message: '', data: searchFixtureApp })
      }),
    )
    const client = createClient()
    client.setQueryData(searchKeys.detail('search-1'), searchFixtureApp)
    const { result } = renderHook(() => useUpdateSearchConfig('search-1'), {
      wrapper: wrapperFor(client),
    })

    await act(async () => {
      await result.current.mutateAsync({ ...toFormValues(searchFixtureApp), kbIds: ['a', 'b'] })
    })

    expect(path).toBe('/api/v1/searches/search-1')
    expect(body).toMatchObject({
      name: 'Wyszukiwarka testowa',
      description: 'Wyszukiwarka demonstracyjna',
      search_config: {
        kb_ids: ['a', 'b'],
        use_kg: false,
        chat_id: 'fake-chat',
        similarity_threshold: 0.2,
      },
    })
    expect(client.getQueryState(searchKeys.detail('search-1'))?.isInvalidated).toBe(true)
  })
})
