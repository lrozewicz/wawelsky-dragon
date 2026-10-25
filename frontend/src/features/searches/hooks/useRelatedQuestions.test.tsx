import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, renderHook, waitFor } from '@testing-library/react'
import { HttpResponse, http } from 'msw'
import type { ReactNode } from 'react'
import { afterEach, describe, expect, it } from 'vitest'

import { apiUrl } from '../../../test/msw/handlers'
import { server } from '../../../test/msw/server'

import { useRelatedQuestions } from './useRelatedQuestions'

afterEach(cleanup)

function createClient(): QueryClient {
  return new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } })
}

function wrapperFor(client: QueryClient) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>
  }
}

const RECOMMENDATION_URL = apiUrl('/api/v1/chat/recommendation')

describe('useRelatedQuestions', () => {
  it('zwraca tablicę pytań z data', async () => {
    const { result } = renderHook(() => useRelatedQuestions('search-1', 'co to smok?', true), {
      wrapper: wrapperFor(createClient()),
    })

    await waitFor(() =>
      expect(result.current.data).toEqual(['Powiązane pytanie 1', 'Powiązane pytanie 2']),
    )
  })

  it('koperta code≠0 daje pustą listę bez rzucania', async () => {
    server.use(
      http.post(RECOMMENDATION_URL, () =>
        HttpResponse.json({ code: 500, message: 'boom', data: null }),
      ),
    )
    const { result } = renderHook(() => useRelatedQuestions('search-1', 'q', true), {
      wrapper: wrapperFor(createClient()),
    })

    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(result.current.data).toEqual([])
    expect(result.current.error).toBeNull()
  })

  it('HTTP 500 daje pustą listę bez rzucania', async () => {
    server.use(
      http.post(RECOMMENDATION_URL, () =>
        HttpResponse.json({ code: 500, message: 'boom', data: null }, { status: 500 }),
      ),
    )
    const { result } = renderHook(() => useRelatedQuestions('search-1', 'q', true), {
      wrapper: wrapperFor(createClient()),
    })

    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(result.current.data).toEqual([])
  })

  it('bez enabled albo bez pytania nie wysyła żądania', async () => {
    let requests = 0
    server.use(
      http.post(RECOMMENDATION_URL, () => {
        requests += 1
        return HttpResponse.json({ code: 0, message: '', data: [] })
      }),
    )
    const disabled = renderHook(() => useRelatedQuestions('search-1', 'q', false), {
      wrapper: wrapperFor(createClient()),
    })
    const noQuestion = renderHook(() => useRelatedQuestions('search-1', null, true), {
      wrapper: wrapperFor(createClient()),
    })

    await new Promise((resolve) => setTimeout(resolve, 10))
    expect(requests).toBe(0)
    expect(disabled.result.current.isFetching).toBe(false)
    expect(noQuestion.result.current.isFetching).toBe(false)
  })
})
