import { QueryClient } from '@tanstack/react-query'
import { HttpResponse, http } from 'msw'
import { describe, expect, it } from 'vitest'

import { apiUrl, fixtureChat, fixtureDataset } from '../../test/msw/handlers'
import { server } from '../../test/msw/server'

import { recentChatsQueryOptions, recentDatasetsQueryOptions } from './queries'

function createClient(): QueryClient {
  return new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } })
}

describe('recentDatasetsQueryOptions', () => {
  it('pyta o 4 ostatnio zmienione datasety i rozpakowuje listę', async () => {
    const seen: URL[] = []
    server.use(
      http.get(apiUrl('/api/v1/datasets'), ({ request }) => {
        seen.push(new URL(request.url))
        return HttpResponse.json({
          code: 0,
          message: 'success',
          data: [fixtureDataset],
          total_datasets: 1,
        })
      }),
    )

    const items = await createClient().fetchQuery(recentDatasetsQueryOptions())

    expect(items).toEqual([fixtureDataset])
    expect(seen[0]?.searchParams.get('page_size')).toBe('4')
    expect(seen[0]?.searchParams.get('orderby')).toBe('update_time')
  })

  it('rzuca ApiError przy kopercie code ≠ 0', async () => {
    server.use(
      http.get(apiUrl('/api/v1/datasets'), () =>
        HttpResponse.json({ code: 101, message: 'boom', data: false }),
      ),
    )

    await expect(createClient().fetchQuery(recentDatasetsQueryOptions())).rejects.toThrow('boom')
  })
})

describe('recentChatsQueryOptions', () => {
  it('pyta o 4 ostatnie czaty i rozpakowuje {chats, total}', async () => {
    let pageSize: string | null = null
    server.use(
      http.get(apiUrl('/api/v1/chats'), ({ request }) => {
        pageSize = new URL(request.url).searchParams.get('page_size')
        return HttpResponse.json({
          code: 0,
          message: 'success',
          data: { chats: [fixtureChat], total: 1 },
        })
      }),
    )

    const items = await createClient().fetchQuery(recentChatsQueryOptions())

    expect(items).toEqual([fixtureChat])
    expect(pageSize).toBe('4')
  })

  it('rzuca ApiError przy błędzie transportu', async () => {
    server.use(
      http.get(apiUrl('/api/v1/chats'), () =>
        HttpResponse.json({ code: 500, message: 'boom' }, { status: 500 }),
      ),
    )

    await expect(createClient().fetchQuery(recentChatsQueryOptions())).rejects.toThrow()
  })
})
